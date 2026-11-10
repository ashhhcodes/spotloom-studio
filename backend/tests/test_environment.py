from __future__ import annotations

import os
from pathlib import Path

from adforge_renderer import environment
from adforge_renderer.database import DatabaseConfig


def test_backend_env_path_is_deterministic_and_process_values_take_precedence(
    monkeypatch, tmp_path: Path
) -> None:
    backend_dir = tmp_path / "backend-config"
    backend_dir.mkdir()
    dotenv_path = backend_dir / ".env"
    dotenv_path.write_text(
        "DATABASE_URL=postgresql+psycopg://file_user:file_pass@localhost/file_db\n"
        "CLERK_ISSUER=https://file-clerk.example\n",
        encoding="utf-8",
    )
    elsewhere = tmp_path / "unrelated-working-directory"
    elsewhere.mkdir()

    monkeypatch.setattr(environment, "_BACKEND_ENV_PATH", dotenv_path)
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://process_user:process_pass@localhost/process_db"
    )
    monkeypatch.delenv("CLERK_ISSUER", raising=False)

    environment.load_backend_environment()

    assert DatabaseConfig.from_environment().url.database == "process_db"
    assert os.environ["CLERK_ISSUER"] == "https://file-clerk.example"
    assert environment._BACKEND_ENV_PATH == dotenv_path


def test_default_backend_env_path_is_anchored_to_module_location() -> None:
    assert environment._BACKEND_ENV_PATH == Path(environment.__file__).resolve().parents[1] / ".env"


def test_database_config_loads_database_url_from_backend_env_file(monkeypatch, tmp_path: Path) -> None:
    dotenv_path = tmp_path / "backend" / ".env"
    dotenv_path.parent.mkdir()
    dotenv_path.write_text(
        "DATABASE_URL=postgresql+psycopg://local_user:local_pass@127.0.0.1/spotloom_dev\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(environment, "_BACKEND_ENV_PATH", dotenv_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = DatabaseConfig.from_environment()

    assert config.url.drivername == "postgresql+psycopg"
    assert config.url.database == "spotloom_dev"
