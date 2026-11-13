from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from adforge_renderer import asset_recovery_cli as cli
from adforge_renderer.asset_recovery_runner import (
    RecoveryRunResult,
    RecoveryRunnerStopReason,
)
from adforge_renderer.asset_service import AssetServiceConfig
from adforge_renderer.local_asset_storage import LocalAssetStorageConfig


def _result(
    *,
    unexpected_failures: int = 0,
    failure_category: str | None = None,
    retry_scheduled: int = 0,
    manual_reconciliation_required: int = 0,
) -> RecoveryRunResult:
    now = datetime.now(timezone.utc)
    not_claimable = 0 if unexpected_failures else 1
    operations = (
        unexpected_failures
        + retry_scheduled
        + manual_reconciliation_required
        + not_claimable
    )
    return RecoveryRunResult(
        invocation_id=uuid4(),
        started_at=now,
        finished_at=now + timedelta(milliseconds=25),
        operations_attempted=operations,
        completed=0,
        already_completed=0,
        not_claimable=not_claimable,
        retry_scheduled=retry_scheduled,
        manual_reconciliation_required=manual_reconciliation_required,
        stale_claim=0,
        unexpected_failures=unexpected_failures,
        failure_category=failure_category,
        stop_reason=(
            RecoveryRunnerStopReason.NO_ELIGIBLE_WORK
            if not unexpected_failures
            else RecoveryRunnerStopReason.UNEXPECTED_ERROR
        ),
        operation_limit_reached=False,
        time_budget_exhausted=False,
        time_budget_exceeded_after_operation=False,
    )


def test_importing_cli_module_has_no_side_effects() -> None:
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", "import adforge_renderer.asset_recovery_cli"],
        cwd=backend,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_help_does_not_initialize_database_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_initialized():
        raise AssertionError("runtime must not be constructed for help")

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", fail_if_initialized)
    monkeypatch.setattr(cli, "_load_configuration", fail_if_initialized)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0


def test_valid_argument_parsing() -> None:
    args = cli._build_parser().parse_args(
        ["run", "--max-operations", "3", "--time-budget-seconds", "1.25"]
    )
    assert args.max_operations == 3
    assert args.time_budget_seconds == 1.25


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-operations", "0"),
        ("--max-operations", "11"),
        ("--max-operations", "one"),
        ("--time-budget-seconds", "0"),
        ("--time-budget-seconds", "-1"),
        ("--time-budget-seconds", "inf"),
        ("--time-budget-seconds", "nan"),
    ],
)
def test_invalid_arguments_are_rejected(option: str, value: str) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["run", option, value])
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "url",
    [
        None,
        "not-a-database-url",
        "postgresql+psycopg://127.0.0.1:5432/spotloom_test",
        "postgresql+psycopg://127.0.0.1:5432/other",
        "postgresql+psycopg://example.invalid:5432/spotloom_local_dev_DB",
        "postgresql+psycopg://127.0.0.1:5433/spotloom_local_dev_DB",
        "postgresql+psycopg://127.0.0.1:5432/spotloom_local_dev_DB?hostaddr=203.0.113.1",
    ],
)
def test_database_target_rejects_unapproved_or_ambiguous_urls(url: str | None) -> None:
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
        cli._validate_database_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://127.0.0.1:5432/%73potloom_local_dev_DB",
        "postgresql+psycopg://[::ffff:127.0.0.1]:5432/spotloom_local_dev_DB",
    ],
)
def test_database_target_rejects_encoded_database_and_ipv4_mapped_ipv6(
    url: str,
) -> None:
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
        cli._validate_database_target(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_database_target_accepts_only_approved_local_development_database(host: str) -> None:
    cli._validate_database_target(
        f"postgresql+psycopg://{host}:5432/spotloom_local_dev_DB"
    )


def test_database_target_accepts_encoded_credentials_without_exposing_them() -> None:
    cli._validate_database_target(
        "postgresql+psycopg://role%40local:p%40ss%3Aword@localhost:5432/"
        "spotloom_local_dev_DB"
    )


class _IdentitySession:
    def __init__(self, row=None, *, fail_query: bool = False) -> None:
        self.row = row
        self.fail_query = fail_query
        self.statements: list[str] = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("SELECT "):
            if self.fail_query:
                raise RuntimeError("private connection detail")
            return _IdentityResult(self.row)
        return object()


class _IdentityResult:
    def __init__(self, row) -> None:
        self._row = row

    def one(self):
        return self._row


class _IdentitySessionFactory:
    def __init__(self, session: _IdentitySession) -> None:
        self.session = session

    @contextmanager
    def begin(self):
        yield self.session


def _verify_identity(row, *, expected_role: str = "spotloom_local_dev_DB") -> _IdentitySession:
    session = _IdentitySession(row)
    cli._verify_database_identity(_IdentitySessionFactory(session), expected_role)
    return session


def test_connected_database_identity_matches_and_runs_in_read_only_transaction() -> None:
    session = _verify_identity(
        ("spotloom_local_dev_DB", "spotloom_local_dev_DB", "127.0.0.1", 5432)
    )
    assert session.statements == [
        "SET TRANSACTION READ ONLY",
        "SELECT current_database(), current_user, inet_server_addr(), inet_server_port()",
    ]


@pytest.mark.parametrize(
    "row",
    [
        ("spotloom_test", "spotloom_local_dev_DB", "127.0.0.1", 5432),
        ("spotloom_local_dev_DB", "another_role", "127.0.0.1", 5432),
        ("spotloom_local_dev_DB", "spotloom_local_dev_DB", "127.0.0.1", 5433),
        ("spotloom_local_dev_DB", "spotloom_local_dev_DB", "203.0.113.7", 5432),
        ("spotloom_local_dev_DB", "spotloom_local_dev_DB", None, 5432),
    ],
)
def test_connected_database_identity_mismatch_fails_closed(row) -> None:
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
        _verify_identity(row)


def test_metadata_query_failure_is_sanitized() -> None:
    session = _IdentitySession(None, fail_query=True)
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError) as raised:
        cli._verify_database_identity(
            _IdentitySessionFactory(session), "spotloom_local_dev_DB"
        )
    assert "private connection detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("row", "fail_query"),
    [
        (("spotloom_test", "spotloom_local_dev_DB", "127.0.0.1", 5432), False),
        (("spotloom_local_dev_DB", "different_role", "127.0.0.1", 5432), False),
        (("spotloom_local_dev_DB", "spotloom_local_dev_DB", "127.0.0.1", 5433), False),
        (("spotloom_local_dev_DB", "spotloom_local_dev_DB", "203.0.113.7", 5432), False),
        (("spotloom_local_dev_DB", "spotloom_local_dev_DB", None, 5432), False),
        (None, True),
    ],
)
def test_cli_does_not_construct_recovery_after_identity_failure_and_disposes_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    row,
    fail_query: bool,
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_configuration",
        lambda: cli._CLIConfiguration(
            LocalAssetStorageConfig(Path("C:/private")),
            AssetServiceConfig(524_288_000, timedelta(seconds=60)),
            "spotloom_local_dev_DB",
        ),
    )
    events: list[str] = []

    class Runtime:
        def session_factory(self):
            events.append("session_factory")
            return _IdentitySessionFactory(
                _IdentitySession(row, fail_query=fail_query)
            )

        def dispose(self):
            events.append("dispose")

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("recovery components must not be constructed")

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", Runtime)
    monkeypatch.setattr(cli, "LocalPrivateAssetStorage", fail_if_constructed)
    monkeypatch.setattr(cli, "LocalUploadRecoveryCoordinator", fail_if_constructed)
    monkeypatch.setattr(cli, "AssetRecoveryRunner", fail_if_constructed)

    assert cli.main(["run"]) == 2
    assert events == ["session_factory", "dispose"]
    assert "spotloom_test" not in capsys.readouterr().err


def test_connection_acquisition_failure_disposes_runtime_before_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_configuration",
        lambda: cli._CLIConfiguration(
            LocalAssetStorageConfig(Path("C:/private")),
            AssetServiceConfig(524_288_000, timedelta(seconds=60)),
            "spotloom_local_dev_DB",
        ),
    )
    events: list[str] = []

    class ConnectionFailure:
        def __enter__(self):
            events.append("connection_attempt")
            raise RuntimeError("sensitive connection string and server detail")

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FailingSessionFactory:
        def begin(self):
            return ConnectionFailure()

    class Runtime:
        def session_factory(self):
            events.append("session_factory")
            return FailingSessionFactory()

        def dispose(self):
            events.append("dispose")

    def fail_if_constructed(*args, **kwargs):
        events.append("recovery_component_constructed")
        raise AssertionError("recovery components must not be constructed")

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", Runtime)
    monkeypatch.setattr(cli, "LocalPrivateAssetStorage", fail_if_constructed)
    monkeypatch.setattr(cli, "LocalUploadRecoveryCoordinator", fail_if_constructed)
    monkeypatch.setattr(cli, "AssetRecoveryRunner", fail_if_constructed)

    assert cli.main(["run"]) == 2
    assert events == ["session_factory", "connection_attempt", "dispose"]
    output = capsys.readouterr()
    assert "sensitive connection string" not in output.out + output.err
    assert "server detail" not in output.out + output.err


@pytest.mark.parametrize(
    "row",
    [
        ("spotloom_local_dev_DB", "spotloom_local_dev_DB", "127.0.0.1"),
        (
            "spotloom_local_dev_DB",
            "spotloom_local_dev_DB",
            "127.0.0.1",
            5432,
            "unexpected-extra-value",
        ),
        (
            "spotloom_local_dev_DB",
            "spotloom_local_dev_DB",
            "private-server-address-value",
            5432,
        ),
        object(),
    ],
    ids=("incomplete-row", "extra-column", "malformed-address", "non-row-result"),
)
def test_malformed_identity_rows_dispose_runtime_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    row,
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_configuration",
        lambda: cli._CLIConfiguration(
            LocalAssetStorageConfig(Path("C:/private")),
            AssetServiceConfig(524_288_000, timedelta(seconds=60)),
            "spotloom_local_dev_DB",
        ),
    )
    events: list[str] = []

    class Runtime:
        def session_factory(self):
            events.append("session_factory")
            return _IdentitySessionFactory(_IdentitySession(row))

        def dispose(self):
            events.append("dispose")

    def fail_if_constructed(*args, **kwargs):
        events.append("recovery_component_constructed")
        raise AssertionError("recovery components must not be constructed")

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", Runtime)
    monkeypatch.setattr(cli, "LocalPrivateAssetStorage", fail_if_constructed)
    monkeypatch.setattr(cli, "LocalUploadRecoveryCoordinator", fail_if_constructed)
    monkeypatch.setattr(cli, "AssetRecoveryRunner", fail_if_constructed)

    assert cli.main(["run"]) == 2
    assert events == ["session_factory", "dispose"]
    output = capsys.readouterr()
    assert "private-server-address-value" not in output.out + output.err
    assert "unexpected-extra-value" not in output.out + output.err


def test_summary_contains_all_runner_fields_without_configuration_or_storage_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._print_result(
        _result(retry_scheduled=1, manual_reconciliation_required=1)
    )
    lines = capsys.readouterr().out.splitlines()
    labels = [line.split(":", 1)[0] for line in lines]
    assert labels == [
        "invocation_id",
        "started_at",
        "finished_at",
        "operations_attempted",
        "completed",
        "already_completed",
        "not_claimable",
        "retry_scheduled",
        "manual_reconciliation_required",
        "stale_claims",
        "unexpected_failures",
        "failure_category",
        "stop_reason",
        "duration_seconds",
        "operation_limit_reached",
        "time_budget_exhausted",
        "time_budget_exceeded_after_operation",
    ]
    assert "retry_scheduled: 1" in lines
    assert "manual_reconciliation_required: 1" in lines
    rendered = "\n".join(lines)
    for forbidden in (
        "DATABASE_URL",
        "SPOTLOOM_ASSET_STORAGE_ROOT",
        "opaque_reference",
        "session_token",
        "private user data",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize("role", [None, "", " ", "invalid role", "x" * 64])
def test_expected_database_role_is_required_and_validated(role: str | None) -> None:
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
        cli._validate_expected_database_role(role)


@pytest.mark.parametrize(
    "value",
    [None, "", " ", "0", "-1", "1.5", "abc", str(10**30)],
)
def test_upload_intent_lifetime_is_required_and_bounded_by_timedelta_domain(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    monkeypatch.setattr(cli, "load_backend_environment", lambda: None)
    monkeypatch.setattr(
        LocalAssetStorageConfig,
        "from_environment",
        lambda: LocalAssetStorageConfig(Path("C:/private")),
    )
    if value is None:
        monkeypatch.delenv("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS", raising=False)
    else:
        monkeypatch.setenv("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS", value)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://127.0.0.1:5432/spotloom_local_dev_DB",
    )
    with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
        cli._load_configuration()


def test_configuration_uses_provisional_quota_and_required_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "load_backend_environment", lambda: None)
    storage = LocalAssetStorageConfig(Path("C:/private"))
    monkeypatch.setattr(LocalAssetStorageConfig, "from_environment", lambda: storage)
    monkeypatch.setenv("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS", "3600")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://localhost:5432/spotloom_local_dev_DB",
    )
    monkeypatch.setenv(
        "SPOTLOOM_RECOVERY_EXPECTED_DATABASE_ROLE", "spotloom_local_dev_DB"
    )
    configuration = cli._load_configuration()
    assert configuration.storage is storage
    assert configuration.service == AssetServiceConfig(
        524_288_000, timedelta(seconds=3600)
    )
    assert configuration.expected_database_role == "spotloom_local_dev_DB"
    assert cli.DEVELOPMENT_PROJECT_QUOTA_LIMIT_BYTES == 524_288_000


@pytest.mark.parametrize("role", [None, "", "invalid role"])
def test_configuration_requires_explicit_expected_database_role(
    monkeypatch: pytest.MonkeyPatch, role: str | None
) -> None:
    monkeypatch.setattr(cli, "load_backend_environment", lambda: None)
    monkeypatch.setattr(
        LocalAssetStorageConfig,
        "from_environment",
        lambda: LocalAssetStorageConfig(Path("C:/private")),
    )
    monkeypatch.setenv("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS", "3600")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://localhost:5432/spotloom_local_dev_DB",
    )
    if role is None:
        monkeypatch.delenv("SPOTLOOM_RECOVERY_EXPECTED_DATABASE_ROLE", raising=False)
    else:
        monkeypatch.setenv("SPOTLOOM_RECOVERY_EXPECTED_DATABASE_ROLE", role)
    monkeypatch.setattr(
        cli,
        "LazyDatabaseRuntime",
        lambda: (_ for _ in ()).throw(AssertionError("runtime constructed too early")),
    )
    assert cli.main(["run"]) == 2


def test_missing_or_invalid_storage_root_fails_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "load_backend_environment", lambda: None)
    monkeypatch.setattr(
        "adforge_renderer.local_asset_storage.load_backend_environment", lambda: None
    )
    for value in (None, "relative/storage/path"):
        if value is None:
            monkeypatch.delenv("SPOTLOOM_ASSET_STORAGE_ROOT", raising=False)
        else:
            monkeypatch.setenv("SPOTLOOM_ASSET_STORAGE_ROOT", value)
        with pytest.raises(cli.AssetRecoveryCLIConfigurationError):
            cli._load_configuration()


def test_invalid_configuration_is_rejected_before_runtime_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_backend_environment", lambda: None)
    monkeypatch.setattr(
        LocalAssetStorageConfig,
        "from_environment",
        lambda: LocalAssetStorageConfig(Path("C:/private")),
    )
    monkeypatch.setenv("SPOTLOOM_MAX_UPLOAD_INTENT_LIFETIME_SECONDS", "60")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://127.0.0.1:5432/spotloom_test",
    )
    monkeypatch.setattr(
        cli,
        "LazyDatabaseRuntime",
        lambda: (_ for _ in ()).throw(AssertionError("runtime constructed too early")),
    )
    assert cli.main(["run"]) == 2
    assert "spotloom_test" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("runner_behavior", "expected_exit"),
    [
        ("result", 0),
        ("retry", 0),
        ("manual", 0),
        ("reported_failure", 1),
        ("exception", 1),
        ("interrupt", 130),
    ],
)
def test_runner_executes_once_and_runtime_is_disposed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runner_behavior: str,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_configuration",
        lambda: cli._CLIConfiguration(
            LocalAssetStorageConfig(Path("C:/private")),
            AssetServiceConfig(524_288_000, timedelta(seconds=60)),
            "spotloom_local_dev_DB",
        ),
    )
    events: list[str] = []

    class Runtime:
        def session_factory(self):
            events.append("session_factory")
            return object()

        def dispose(self):
            events.append("dispose")

    class Storage:
        def __init__(self, config):
            events.append("storage")

    class Coordinator:
        def __init__(self, *args):
            events.append("coordinator")

    class Runner:
        def __init__(self, *args, **kwargs):
            events.append("runner")

        def run(self):
            events.append("run")
            if runner_behavior == "exception":
                raise RuntimeError("sensitive database detail")
            if runner_behavior == "interrupt":
                raise KeyboardInterrupt()
            if runner_behavior == "reported_failure":
                return _result(unexpected_failures=1, failure_category="database_error")
            if runner_behavior == "retry":
                return _result(retry_scheduled=1)
            if runner_behavior == "manual":
                return _result(manual_reconciliation_required=1)
            return _result()

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", Runtime)
    monkeypatch.setattr(
        cli,
        "_verify_database_identity",
        lambda session_factory, expected_role: events.append("verify_identity"),
    )
    monkeypatch.setattr(cli, "LocalPrivateAssetStorage", Storage)
    monkeypatch.setattr(cli, "LocalUploadRecoveryCoordinator", Coordinator)
    monkeypatch.setattr(cli, "AssetRecoveryRunner", Runner)

    assert cli.main(["run"]) == expected_exit
    assert events == [
        "session_factory",
        "verify_identity",
        "storage",
        "coordinator",
        "runner",
        "run",
        "dispose",
    ]
    output = capsys.readouterr()
    assert "sensitive database detail" not in output.out + output.err
    if runner_behavior == "result":
        assert "operations_attempted: 1" in output.out
        assert "stop_reason: no_eligible_work" in output.out
    elif runner_behavior == "retry":
        assert "retry_scheduled: 1" in output.out
        assert "unexpected_failures: 0" in output.out
    elif runner_behavior == "manual":
        assert "manual_reconciliation_required: 1" in output.out
        assert "unexpected_failures: 0" in output.out


def test_system_exit_is_not_swallowed_and_runtime_is_disposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "_load_configuration",
        lambda: cli._CLIConfiguration(
            LocalAssetStorageConfig(Path("C:/private")),
            AssetServiceConfig(524_288_000, timedelta(seconds=60)),
            "spotloom_local_dev_DB",
        ),
    )
    events: list[str] = []

    class Runtime:
        def session_factory(self):
            return object()

        def dispose(self):
            events.append("dispose")

    class Runner:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            raise SystemExit(17)

    monkeypatch.setattr(cli, "LazyDatabaseRuntime", Runtime)
    monkeypatch.setattr(cli, "_verify_database_identity", lambda *args: None)
    monkeypatch.setattr(cli, "LocalPrivateAssetStorage", lambda config: object())
    monkeypatch.setattr(cli, "LocalUploadRecoveryCoordinator", lambda *args: object())
    monkeypatch.setattr(cli, "AssetRecoveryRunner", Runner)

    with pytest.raises(SystemExit) as raised:
        cli.main(["run"])
    assert raised.value.code == 17
    assert events == ["dispose"]
