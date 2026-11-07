import json
from types import SimpleNamespace

import pytest
from api.routers.api.report import route as report_route
from fastapi.testclient import TestClient


def _payload(**overrides: object) -> dict:
    payload = {
        "mode": "structure_and_design",
        "clientName": "EDF",
        "clientUrl": "https://www.edf.fr",
        "organizationId": 293168,
        "networkId": 2120,
        "exerciceIdNMinus1": 12310,
        "yearN": 2025,
        "yearNMinus1": 2024,
        "pastExercices": 5,
        "indicators": [
            {
                "theme": "Environnement",
                "subTheme": "GES",
                "category": "Scope 1",
                "name": "Émissions GES",
                "type": "Nombre",
                "parentId": 412225,
            },
            {
                "theme": "Social",
                "subTheme": "Diversité",
                "category": "",
                "name": "Note NA",
                "type": "Narratif",
                "parentId": 7658,
                "flag": "NA",
            },
        ],
    }
    payload.update(overrides)
    return payload


def _completion(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


@pytest.fixture
def client() -> TestClient:
    from conftest import build_app

    return TestClient(build_app())


def test_report_structure_and_design_returns_json_and_css(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    model_output = {
        "reportJson": {"time": 1, "version": "2.30.5", "blocks": []},
        "css": ":root { --primary: #07387a; }",
        "excluded": ["Note NA"],
        "notes": "",
    }

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return _completion(model_output)

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))

    res = client.post("/api/report", json=_payload())

    assert res.status_code == 200
    body = res.json()
    assert body["reportJson"]["version"] == "2.30.5"
    assert body["css"].startswith(":root")
    assert body["excluded"] == ["Note NA"]
    messages = calls[0]["messages"]
    assert messages[0]["role"] == "system" and "Editor.js" in messages[0]["content"]
    assert calls[0]["model"] == "mistral-small-latest"
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_report_design_only_needs_no_indicators_and_returns_no_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(complete=lambda **kwargs: _completion({"css": "body{}", "excluded": []}))
        ),
    )

    res = client.post("/api/report", json=_payload(mode="design_only", indicators=[]))

    assert res.status_code == 200
    body = res.json()
    assert body["reportJson"] is None
    assert body["css"] == "body{}"


def test_report_structure_only_returns_json_and_no_css(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(
                complete=lambda **kwargs: _completion({"reportJson": {"blocks": []}, "css": "body{}"})
            )
        ),
    )

    res = client.post("/api/report", json=_payload(mode="structure_only"))

    assert res.status_code == 200
    body = res.json()
    assert body["reportJson"] == {"blocks": []}
    assert body["css"] is None


def test_report_rejects_invalid_mode(client: TestClient) -> None:
    res = client.post("/api/report", json=_payload(mode="everything"))
    assert res.status_code == 422


def test_report_rejects_missing_ids(client: TestClient) -> None:
    payload = _payload()
    del payload["networkId"]
    res = client.post("/api/report", json=payload)
    assert res.status_code == 422
