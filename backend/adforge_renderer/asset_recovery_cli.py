"""Explicit, one-shot development CLI for bounded local asset recovery.

Importing this module has no runtime side effects. It does not connect to a
database, create storage directories, or start recovery until ``main`` is run.
The database allowlist and quota in this module are development safeguards,
not production security guarantees or approved production limits.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
import ipaddress
import math
import os
import re
import sys
from typing import Sequence

from sqlalchemy import text

from .asset_storage_provider import StorageConfigurationError
from .asset_recovery_coordinator import LocalUploadRecoveryCoordinator
from .asset_recovery_runner import (
    DEFAULT_MAX_OPERATIONS,
    DEFAULT_TIME_BUDGET_SECONDS,
    AssetRecoveryRunner,
    RecoveryRunResult,
)
from .asset_service import AssetServiceConfig, AssetServiceConfigurationError
from .database.config import DatabaseConfig, DatabaseConfigurationError
from .database.runtime import LazyDatabaseRuntime
from .environment import load_backend_environment
from .local_asset_storage import (
    LocalAssetStorageConfig,
    LocalPrivateAssetStorage,
)


# Provisional local-development setting only; never a production quota default.
DEVELOPMENT_PROJECT_QUOTA_LIMIT_BYTES = 524_288_000
_SECONDS_PER_DAY = 24 * 60 * 60
_MAX_TIMEDELTA_SECONDS = timedelta.max.days * _SECONDS_PER_DAY + timedelta.max.seconds
_ALLOWED_DATABASE_NAME = "spotloom_local_dev_DB"
_ALLOWED_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1"})
_ALLOWED_DATABASE_PORT = 5432


class AssetRecoveryCLIConfigurationError(ValueError):
    """Safe configuration failure that never contains supplied secret values."""


@dataclass(frozen=True, slots=True)
class _CLIConfiguration:
    storage: LocalAssetStorageConfig
    service: AssetServiceConfig
    expected_database_role: str


def _parse_max_operations(raw: str) -> int:
    try:
        value = int(raw, 10)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer from 1 to 10") from None
    if not 1 <= value <= DEFAULT_MAX_OPERATIONS:
        raise argparse.ArgumentTypeError("must be between 1 and 10")
    return value


def _parse_time_budget(raw: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a positive finite number") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m adforge_renderer.asset_recovery_cli",
        description="Run one bounded batch of local asset recovery operations.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a single bounded recovery batch")
    run.add_argument(
        "--max-operations", type=_parse_max_operations,
        default=DEFAULT_MAX_OPERATIONS,
        help="maximum operations in this invocation (1-10; default: 10)",
    )
    run.add_argument(
        "--time-budget-seconds", type=_parse_time_budget,
        default=DEFAULT_TIME_BUDGET_SECONDS,
        help="soft time budget in seconds (default: 60); does not cancel in-flight work",
    )
    return parser


def _load_configuration() -> _CLIConfiguration:
    """Validate all configuration before runtime or storage initialization."""
    load_backend_environment()

    try:
        storage = LocalAssetStorageConfig.from_environment()
    except StorageConfigurationError:
        raise AssetRecoveryCLIConfigurationError(
            "SPOTLOOM_ASSET_STORAGE_ROOT is missing or invalid."
        ) from None

    raw_lifetime = os.environ.get("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS")
    if (
        not isinstance(raw_lifetime, str)
        or not raw_lifetime
        or raw_lifetime != raw_lifetime.strip()
        or not raw_lifetime.isascii()
        or not raw_lifetime.isdigit()
    ):
        raise AssetRecoveryCLIConfigurationError(
            "SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS must be a positive integer."
        )
    lifetime_seconds = int(raw_lifetime, 10)
    if not 0 < lifetime_seconds <= _MAX_TIMEDELTA_SECONDS:
        raise AssetRecoveryCLIConfigurationError(
            "SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS is outside the supported range."
        )
    lifetime = timedelta(
        days=lifetime_seconds // _SECONDS_PER_DAY,
        seconds=lifetime_seconds % _SECONDS_PER_DAY,
    )
    try:
        service = AssetServiceConfig(
            project_quota_limit_bytes=DEVELOPMENT_PROJECT_QUOTA_LIMIT_BYTES,
            maximum_upload_intent_lifetime=lifetime,
        )
    except AssetServiceConfigurationError:
        raise AssetRecoveryCLIConfigurationError(
            "Asset service development configuration is invalid."
        ) from None

    _validate_database_target(os.environ.get("DATABASE_URL"))
    expected_role = _validate_expected_database_role(
        os.environ.get("SPOTLOOM_RECOVERY_EXPECTED_DATABASE_ROLE")
    )
    return _CLIConfiguration(
        storage=storage,
        service=service,
        expected_database_role=expected_role,
    )


def _validate_database_target(raw_database_url: str | None) -> None:
    try:
        database = DatabaseConfig.from_url(raw_database_url or "")
    except DatabaseConfigurationError:
        raise AssetRecoveryCLIConfigurationError(
            "DATABASE_URL is missing or invalid."
        ) from None
    url = database.url
    if (
        url.database != _ALLOWED_DATABASE_NAME
        or url.host not in _ALLOWED_DATABASE_HOSTS
        or url.port != _ALLOWED_DATABASE_PORT
        or bool(url.query)
    ):
        raise AssetRecoveryCLIConfigurationError(
            "DATABASE_URL is not an approved local development target."
        )


def _validate_expected_database_role(raw_role: str | None) -> str:
    if (
        not isinstance(raw_role, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", raw_role)
    ):
        raise AssetRecoveryCLIConfigurationError(
            "SPOTLOOM_RECOVERY_EXPECTED_DATABASE_ROLE is missing or invalid."
        )
    return raw_role


def _verify_database_identity(session_factory, expected_role: str) -> None:
    """Fail closed unless connected PostgreSQL metadata matches local dev."""
    try:
        with session_factory.begin() as session:
            # This must be the first statement in the transaction.
            session.execute(text("SET TRANSACTION READ ONLY"))
            row = session.execute(
                text(
                    "SELECT current_database(), current_user, "
                    "inet_server_addr(), inet_server_port()"
                )
            ).one()
    except Exception:
        raise AssetRecoveryCLIConfigurationError(
            "Connected database identity could not be verified."
        ) from None

    try:
        database_name, actual_role, server_address, server_port = row
        server_ip = ipaddress.ip_address(str(server_address))
    except (TypeError, ValueError):
        raise AssetRecoveryCLIConfigurationError(
            "Connected database identity could not be verified."
        ) from None

    if (
        database_name != _ALLOWED_DATABASE_NAME
        or actual_role != expected_role
        or server_address is None
        or not server_ip.is_loopback
        or server_port != _ALLOWED_DATABASE_PORT
    ):
        raise AssetRecoveryCLIConfigurationError(
            "Connected database identity does not match the approved local target."
        )


def _print_result(result: RecoveryRunResult) -> None:
    duration = (result.finished_at - result.started_at).total_seconds()
    fields: tuple[tuple[str, object], ...] = (
        ("invocation_id", result.invocation_id),
        ("started_at", result.started_at.isoformat()),
        ("finished_at", result.finished_at.isoformat()),
        ("operations_attempted", result.operations_attempted),
        ("completed", result.completed),
        ("already_completed", result.already_completed),
        ("not_claimable", result.not_claimable),
        ("retry_scheduled", result.retry_scheduled),
        ("manual_reconciliation_required", result.manual_reconciliation_required),
        ("stale_claims", result.stale_claim),
        ("unexpected_failures", result.unexpected_failures),
        ("failure_category", result.failure_category or "none"),
        ("stop_reason", result.stop_reason.value),
        ("duration_seconds", f"{duration:.3f}"),
        ("operation_limit_reached", result.operation_limit_reached),
        ("time_budget_exhausted", result.time_budget_exhausted),
        ("time_budget_exceeded_after_operation", result.time_budget_exceeded_after_operation),
    )
    for name, value in fields:
        print(f"{name}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit recovery batch; return documented process exit status."""
    args = _build_parser().parse_args(argv)
    runtime: LazyDatabaseRuntime | None = None
    exit_code = 1
    try:
        configuration = _load_configuration()
        # The target is validated before runtime construction or engine creation.
        runtime = LazyDatabaseRuntime()
        session_factory = runtime.session_factory()
        _verify_database_identity(
            session_factory, configuration.expected_database_role
        )
        storage = LocalPrivateAssetStorage(configuration.storage)
        coordinator = LocalUploadRecoveryCoordinator(
            session_factory, configuration.service, storage
        )
        runner = AssetRecoveryRunner(
            coordinator,
            max_operations=args.max_operations,
            time_budget_seconds=args.time_budget_seconds,
        )
        result = runner.run()
        _print_result(result)
        exit_code = 1 if result.unexpected_failures else 0
    except KeyboardInterrupt:
        print(
            "Asset recovery interrupted; in-flight synchronous work may have completed.",
            file=sys.stderr,
        )
        exit_code = 130
    except (
        AssetRecoveryCLIConfigurationError,
        DatabaseConfigurationError,
        AssetServiceConfigurationError,
        StorageConfigurationError,
    ):
        print("Asset recovery configuration is invalid or incomplete.", file=sys.stderr)
        exit_code = 2
    except Exception:
        # Never include raw exception text, which may contain sensitive data.
        print("Asset recovery execution failed (operational_error).", file=sys.stderr)
        exit_code = 1
    finally:
        if runtime is not None:
            try:
                runtime.dispose()
            except Exception:
                print(
                    "Asset recovery runtime disposal failed (operational_error).",
                    file=sys.stderr,
                )
                if exit_code == 0:
                    exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
