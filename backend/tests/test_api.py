from __future__ import annotations

import importlib
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adforge_renderer import api


def test_health_returns_stable_json() -> None:
    with TestClient(api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


def test_health_does_not_call_external_services_or_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("health must not use network or subprocess operations")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setenv("ADFORGE_TEST_SECRET", "must-not-be-returned")

    with TestClient(api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert "must-not-be-returned" not in response.text
    assert str(Path.cwd()) not in response.text
    assert "traceback" not in response.text.lower()


def test_import_does_not_start_server(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn
    from adforge_renderer import cli, creative_cli, scan_cli

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("importing the app must not start a server or execute CLI work")

    monkeypatch.setattr(uvicorn, "run", forbidden)
    for module in (cli, creative_cli, scan_cli):
        monkeypatch.setattr(module, "main", forbidden)
    imported = importlib.reload(api)
    assert imported.app is not None


def test_explicit_startup_passes_validated_loopback_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: calls.append((app, host, port)))

    api.main(["--host", "::1", "--port", "8123"])

    assert calls == [(api.app, "::1", 8123)]


def test_startup_defaults_to_loopback_and_port_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: calls.append((app, host, port)))

    api.main([])

    assert calls == [(api.app, "127.0.0.1", 8000)]


def test_localhost_configuration_is_normalized_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: calls.append((app, host, port)))

    api.main(["--host", "localhost"])

    assert calls == [(api.app, "127.0.0.1", 8000)]


@pytest.mark.parametrize(
    "arguments",
    [["--host", "0.0.0.0"], ["--host", "example.com"], ["--port", "0"], ["--port", "65536"]],
)
def test_startup_rejects_unsafe_or_invalid_configuration(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        api.main(arguments)

    assert error.value.code == 2


def test_no_business_routes_are_exposed() -> None:
    with TestClient(api.app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
