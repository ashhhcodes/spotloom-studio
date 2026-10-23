from __future__ import annotations

import importlib
import copy
import json
import logging
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from adforge_renderer import api


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract-compatibility.json"
VALID = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["validNorthstar"]


def valid_request() -> dict[str, object]:
    return copy.deepcopy({
        "facts": {"facts": VALID["facts"]},
        "brief": VALID["brief"],
        "storyboard": VALID["storyboard"],
    })


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


def test_only_health_and_preproduction_validation_routes_are_exposed() -> None:
    with TestClient(api.app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/scan").status_code == 404
        assert client.post("/scan", json={"url": "https://example.com"}).status_code == 404
        assert client.post("/generate", json={}).status_code == 404
        assert client.post("/render", json={}).status_code == 404

    routes = {
        (route.path, method)
        for route in api.app.routes
        for method in getattr(route, "methods", set())
    }
    assert routes == {
        ("/health", "GET"),
        ("/validate/preproduction", "POST"),
    }


def test_preproduction_validation_returns_schema_result_and_derived_runtime() -> None:
    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=valid_request())

    assert response.status_code == 200
    body = response.json()
    assert body["requestSchemaValid"] is True
    assert body["evaluationStatus"] == "evaluated-with-limitations"
    assert body["readinessStatus"] == "needs-attention"
    assert body["briefConfirmationSignal"] == "not-confirmed"
    assert body["factualVerification"] == "not-performed"
    assert body["storyboardSummary"] == {
        "sceneCount": 3,
        "plannedRuntimeSeconds": 15,
        "targetRuntimeSeconds": 15,
        "runtimeDifferenceSeconds": 0,
        "runtimeUnavailableReason": None,
    }
    findings = body["findings"]
    assert body["summary"] == {
        "blockerCount": sum(finding["blocksReadiness"] for finding in findings),
        "warningCount": sum(finding["severity"] == "warning" for finding in findings),
        "infoCount": sum(finding["severity"] == "info" for finding in findings),
    }
    assert "brief.confirmation.required" in {finding["id"] for finding in findings}


def test_runtime_is_recomputed_from_submitted_scene_durations() -> None:
    payload = valid_request()
    payload["storyboard"]["scenes"][0]["durationSeconds"] = 1
    payload["storyboard"]["scenes"][1]["durationSeconds"] = 60
    payload["storyboard"]["scenes"][2]["durationSeconds"] = 1

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["storyboardSummary"]["plannedRuntimeSeconds"] == 62
    assert body["storyboardSummary"]["runtimeDifferenceSeconds"] == 47
    assert "runtime.target-mismatch" in {finding["id"] for finding in body["findings"]}


@pytest.mark.parametrize("durations, expected_difference", [([5, 5, 4], -1), ([6, 6, 6], 3)])
def test_runtime_shorter_or_longer_than_target_emits_warning(durations, expected_difference: int) -> None:
    payload = valid_request()
    for scene_value, duration in zip(payload["storyboard"]["scenes"], durations, strict=True):
        scene_value["durationSeconds"] = duration

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["storyboardSummary"]["runtimeDifferenceSeconds"] == expected_difference
    mismatch = next(finding for finding in body["findings"] if finding["id"] == "runtime.target-mismatch")
    assert mismatch["severity"] == "warning"
    assert mismatch["blocksReadiness"] is False


def test_exact_runtime_match_does_not_emit_mismatch_finding() -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["readinessStatus"] == "ready-for-human-review"
    assert "runtime.target-mismatch" not in {finding["id"] for finding in body["findings"]}


def test_empty_storyboard_is_valid_but_runtime_is_unavailable() -> None:
    payload = valid_request()
    payload["storyboard"]["scenes"] = []

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["requestSchemaValid"] is True
    assert body["readinessStatus"] == "needs-attention"
    assert body["storyboardSummary"]["plannedRuntimeSeconds"] is None
    assert body["storyboardSummary"]["runtimeUnavailableReason"] == "empty"
    assert "storyboard.empty" in {finding["id"] for finding in body["findings"]}


@pytest.mark.parametrize(
    "status, expected_severity",
    [("approved", "info"), ("unreviewed", "warning"), ("rejected", "warning")],
)
def test_exact_claim_matches_use_caller_review_status_without_verification(
    status: str, expected_severity: str,
) -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True
    fact = payload["facts"]["facts"][0]
    fact["status"] = status
    payload["storyboard"]["scenes"][0]["onScreenText"] = "  SMALL-BATCH   ROASTED COFFEE\n"
    payload["storyboard"]["scenes"][0]["narration"] = "small-batch roasted coffee"

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    body = response.json()
    match = next(
        finding for finding in body["findings"]
        if finding["id"] == "grounding.exact-match.northstar-scene-opening.product"
    )
    assert match["severity"] == expected_severity
    assert match["blocksReadiness"] is False
    assert match["affectedFactId"] == "product"
    assert match["affectedSceneId"] == "northstar-scene-opening"
    assert "on-screen text and narration" in match["explanation"]
    assert "does not establish truth" in match["explanation"]
    assert body["factualVerification"] == "not-performed"
    assert body["factSummary"]["callerMarkedApproved"] == (2 if status == "approved" else 1)
    assert body["briefConfirmationSignal"] == "caller-declared-confirmed"


def test_paraphrases_and_visual_direction_do_not_create_fact_matches() -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True
    scene_value = payload["storyboard"]["scenes"][0]
    scene_value["visualDirection"] = "Small-batch roasted coffee"
    scene_value["onScreenText"] = "Coffee roasted in small batches"
    scene_value["narration"] = "A thoughtful everyday cup"

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    assert not any(
        finding["category"] == "grounding" and finding["affectedFactId"]
        for finding in response.json()["findings"]
    )


def test_claim_normalization_matches_javascript_whitespace_rules() -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True
    payload["storyboard"]["scenes"][0]["onScreenText"] = "\ufeffSmall-batch\u00a0roasted\u3000coffee\ufeff"

    with TestClient(api.app) as client:
        matches_js_whitespace = client.post("/validate/preproduction", json=payload)

    assert matches_js_whitespace.status_code == 200
    assert "grounding.exact-match.northstar-scene-opening.product" in {
        finding["id"] for finding in matches_js_whitespace.json()["findings"]
    }

    payload["storyboard"]["scenes"][0]["onScreenText"] = "Small-batch\u0085roasted coffee"
    with TestClient(api.app) as client:
        does_not_match_js_whitespace = client.post("/validate/preproduction", json=payload)

    assert does_not_match_js_whitespace.status_code == 200
    assert "grounding.exact-match.northstar-scene-opening.product" not in {
        finding["id"] for finding in does_not_match_js_whitespace.json()["findings"]
    }


def test_storyboard_content_findings_match_frontend_conditions() -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True
    scenes = payload["storyboard"]["scenes"]
    scenes[0]["narrativePurpose"] = "  "
    scenes[1]["visualDirection"] = ""

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    findings = {finding["id"]: finding for finding in response.json()["findings"]}
    assert findings["storyboard.purpose-missing.northstar-scene-opening"]["blocksReadiness"] is True
    assert findings["storyboard.visual-direction-missing.northstar-scene-middle"]["blocksReadiness"] is True


def test_storyboard_without_any_previewable_content_has_one_content_blocker() -> None:
    payload = valid_request()
    payload["brief"]["requirementsConfirmed"] = True
    for scene_value in payload["storyboard"]["scenes"]:
        scene_value["visualDirection"] = ""
        scene_value["onScreenText"] = ""
        scene_value["narration"] = ""

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 200
    findings = response.json()["findings"]
    assert "storyboard.no-usable-content" in {finding["id"] for finding in findings}
    assert not any(finding["id"].startswith("storyboard.visual-direction-missing.") for finding in findings)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fact: fact.pop("source"),
        lambda fact: fact.update(source={"kind": "website", "reference": "https://user:secret@example.test"}),
    ],
)
def test_missing_or_malformed_provenance_is_a_sanitized_schema_error(mutate) -> None:
    payload = valid_request()
    mutate(payload["facts"]["facts"][0])

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 422
    assert response.json()["requestSchemaValid"] is False
    assert "secret" not in response.text
    assert "https://" not in response.text


def test_client_supplied_summary_counts_are_not_accepted() -> None:
    payload = valid_request()
    payload.update(blockerCount=0, warningCount=0, infoCount=0, eligibleFactIds=["message"])

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 422
    assert response.json()["requestSchemaValid"] is False


@pytest.mark.parametrize(
    "payload_mutation, expected_path",
    [
        (lambda payload: payload["brief"].update(targetAudience=""), "brief.targetAudience"),
        (lambda payload: payload["brief"].update(objective="brand-lift"), "brief.objective"),
        (lambda payload: payload["brief"].update(unexpected="value"), "brief.extra_field"),
        (lambda payload: payload["storyboard"].update(plannedRuntimeSeconds=999), "storyboard.extra_field"),
    ],
)
def test_schema_issues_are_sanitized_and_change_with_input(payload_mutation, expected_path: str) -> None:
    payload = valid_request()
    payload_mutation(payload)

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["requestSchemaValid"] is False
    assert body["evaluationStatus"] == "not-evaluated"
    assert body["plannedRuntimeSeconds"] is None
    assert body["detail"] == "Request does not match the supported pre-production contract."
    assert any(issue["path"] == expected_path for issue in body["issues"])
    assert all(set(issue) == {"path", "code", "message"} for issue in body["issues"])
    assert all(issue["message"] == "Value does not match the supported contract." for issue in body["issues"])


@pytest.mark.parametrize("duration", [None, 1.5, 0, -1, 61])
def test_invalid_scene_durations_are_rejected_without_reflecting_values(duration) -> None:
    payload = valid_request()
    scene_value = payload["storyboard"]["scenes"][0]
    if duration is None:
        del scene_value["durationSeconds"]
    else:
        scene_value["durationSeconds"] = duration

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["requestSchemaValid"] is False
    assert body["plannedRuntimeSeconds"] is None
    assert any(issue["path"].endswith("durationSeconds") for issue in body["issues"])
    assert all(issue["message"] == "Value does not match the supported contract." for issue in body["issues"])
    assert "input" not in body


def test_malformed_json_and_missing_required_fields_return_sanitized_422() -> None:
    with TestClient(api.app) as client:
        malformed = client.post(
            "/validate/preproduction",
            content='{"facts":',
            headers={"content-type": "application/json"},
        )
        missing = client.post("/validate/preproduction", json={"brief": VALID["brief"]})

    assert malformed.status_code == missing.status_code == 422
    expected_error = {
        "requestSchemaValid": False,
        "evaluationStatus": "not-evaluated",
        "detail": "Invalid request body.",
        "issues": [],
        "plannedRuntimeSeconds": None,
    }
    assert malformed.json() == missing.json() == expected_error
    assert "traceback" not in malformed.text.lower()
    assert str(Path.cwd()) not in missing.text


def test_request_cannot_supply_runtime_or_readiness_as_authoritative() -> None:
    payload = valid_request()
    payload["plannedRuntimeSeconds"] = 999
    payload["readiness"] = "ready"

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=payload)

    assert response.status_code == 422
    assert response.json()["requestSchemaValid"] is False
    assert response.json()["evaluationStatus"] == "not-evaluated"


def test_duplicate_scene_ids_and_collection_bounds_are_rejected() -> None:
    duplicate = valid_request()
    duplicate["storyboard"]["scenes"][1]["id"] = duplicate["storyboard"]["scenes"][0]["id"]
    too_many = valid_request()
    too_many["storyboard"]["scenes"] = [
        {**VALID["storyboard"]["scenes"][0], "id": f"scene-{index}"}
        for index in range(33)
    ]
    too_many_facts = valid_request()
    too_many_facts["facts"]["facts"] = [
        {**VALID["facts"][0], "id": f"fact-{index}"} for index in range(33)
    ]

    with TestClient(api.app) as client:
        duplicate_response = client.post("/validate/preproduction", json=duplicate)
        bounded_response = client.post("/validate/preproduction", json=too_many)
        fact_bound_response = client.post("/validate/preproduction", json=too_many_facts)

    assert duplicate_response.status_code == bounded_response.status_code == fact_bound_response.status_code == 422
    assert duplicate_response.json()["requestSchemaValid"] is False
    assert any(issue["path"] == "storyboard" for issue in duplicate_response.json()["issues"])
    assert any(issue["path"] == "storyboard.scenes" for issue in bounded_response.json()["issues"])
    assert any(issue["path"] == "facts.facts" for issue in fact_bound_response.json()["issues"])


def test_identical_requests_return_equivalent_results() -> None:
    payload = valid_request()

    with TestClient(api.app) as client:
        first = client.post("/validate/preproduction", json=payload)
        second = client.post("/validate/preproduction", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [finding["id"] for finding in first.json()["findings"]] == [
        finding["id"] for finding in second.json()["findings"]
    ]


def test_unexpected_errors_are_logged_without_details_or_returned_to_caller(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-path-or-token"

    def fail(**kwargs: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(api, "validate_contract_input", fail)
    with caplog.at_level(logging.ERROR, logger=api.__name__), TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=valid_request())

    assert response.status_code == 500
    assert response.json() == {
        "evaluationStatus": "failed",
        "detail": "Pre-production validation could not be completed.",
    }
    assert secret not in response.text
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_validation_endpoint_has_no_network_subprocess_or_filesystem_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation endpoint must not perform external or persistent I/O")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=valid_request())

    assert response.status_code == 200
