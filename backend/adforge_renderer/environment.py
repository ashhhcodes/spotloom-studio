"""Deterministic local backend environment loading."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


_BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_backend_environment() -> None:
    """Load backend/.env without overriding variables supplied by the process."""
    load_dotenv(dotenv_path=_BACKEND_ENV_PATH, override=False, verbose=False)
