import io
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


@pytest.fixture(autouse=True)
def fake_caller_token():
    from utils.mistral import CallerCredentials, install_caller_credentials

    install_caller_credentials(lambda: CallerCredentials(server_url="https://gateway.test/v1/proxy", token="tok-test"))
    yield
    install_caller_credentials(None)


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
    assert calls[0]["model"] == "mistral-large-4"
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


def test_report_structure_only_works_without_client_url(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(complete=lambda **kwargs: _completion({"reportJson": {"blocks": []}}))
        ),
    )
    payload = _payload(mode="structure_only")
    del payload["clientUrl"]
    res = client.post("/api/report", json=payload)
    assert res.status_code == 200
    assert res.json()["reportJson"] == {"blocks": []}


def test_report_design_requires_client_url(client: TestClient) -> None:
    payload = _payload(mode="design_only", indicators=[])
    del payload["clientUrl"]
    res = client.post("/api/report", json=payload)
    assert res.status_code == 422


def test_report_refine_returns_updated_livrables(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    updated = {"reportJson": {"blocks": [{"type": "header"}]}, "css": ":root{--primary:#000}", "notes": "couleur changée"}

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return _completion(updated)

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))

    res = client.post(
        "/api/report/refine",
        json={
            "mode": "structure_and_design",
            "instruction": "Mets le bleu EDF en #07387a et ajoute un chart GES",
            "clientName": "EDF",
            "clientUrl": "https://www.edf.fr",
            "organizationId": 293168,
            "networkId": 2120,
            "reportJson": {"blocks": []},
            "css": "body{}",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["reportJson"] == {"blocks": [{"type": "header"}]}
    assert body["css"] == ":root{--primary:#000}"
    assert body["notes"] == "couleur changée"
    assert calls[0]["model"] == "mistral-large-4"
    assert "RAFFINEMENT" in calls[0]["messages"][0]["content"]


def test_report_chat_asks_for_missing_info(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(complete=lambda **kwargs: _completion({"reply": "Quel est le nom du client ?", "done": False}))
        ),
    )
    res = client.post("/api/report/chat", json={"mode": "structure_and_design", "messages": []})
    assert res.status_code == 200
    body = res.json()
    assert body["done"] is False
    assert body["reply"]
    assert body["historyId"] is None


def test_report_chat_generates_and_saves_history(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    store_path = tmp_path / "history.json"
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(store_path))
    output = {"reply": "Voici le livrable.", "done": True, "reportJson": {"blocks": []}, "css": "body{}", "excluded": ["Note NA"]}
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **kwargs: _completion(output))),
    )
    res = client.post(
        "/api/report/chat",
        json={"mode": "structure_and_design", "messages": [{"role": "user", "content": "Client EDF"}], "csv": "Thématique;Indicateur;Type;ID Parent\nEnvironnement;Émissions GES;Nombre;412225", "reportJson": {"blocks": []}, "forcePhase": "css"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["done"] is True
    assert body["reportJson"] == {"blocks": []}
    assert body["historyId"]

    listing = client.get("/api/report/history")
    assert listing.status_code == 200
    entries = listing.json()["entries"]
    assert len(entries) == 1 and entries[0]["id"] == body["historyId"]

    detail = client.get(f"/api/report/history/{body['historyId']}")
    assert detail.status_code == 200
    assert detail.json()["css"] == "body{}"

    missing = client.get("/api/report/history/doesnotexist")
    assert missing.status_code == 404


def test_parse_csv_indicators_maps_french_headers() -> None:
    from api.routers.api.report.chat import parse_csv_indicators

    indicators, errors = parse_csv_indicators(
        "Thématique;Sous-thématique;Indicateur;Type;ID Parent;NA/NM\n"
        "Environnement;GES;Émissions GES;Nombre;412225;\n"
        "Social;Diversité;Note;Narratif;7658;NA\n"
    )
    assert errors == []
    assert indicators[0]["theme"] == "Environnement"
    assert indicators[0]["parentId"] == 412225
    assert indicators[1]["flag"] == "NA"


def test_report_chat_returns_clean_502_when_model_output_is_not_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(complete=lambda **kwargs: _completion_raw("Internal Server Error"))
        ),
    )
    res = client.post("/api/report/chat", json={"mode": "design_only", "messages": [{"role": "user", "content": "EDF"}]})
    assert res.status_code == 502
    assert "Zai" in res.json()["detail"]


def _completion_raw(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_report_chat_repairs_done_with_empty_css(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    outputs = iter([
        {"reply": "Merci ! Je vais extraire la charte…", "done": True, "css": None},
        {"reply": "Voici le CSS.", "done": True, "css": ":root{--primary:#07387a}"},
    ])
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **kwargs: _completion(next(outputs)))),
    )
    res = client.post("/api/report/chat", json={"mode": "design_only", "messages": [{"role": "user", "content": "EDF https://www.edf.fr"}]})
    assert res.status_code == 200
    body = res.json()
    assert body["done"] is True
    assert body["css"] == ":root{--primary:#07387a}"


def test_complete_json_falls_back_to_faster_model_on_504(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    seen_models: list[str] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            seen_models.append(str(kwargs["model"]))
            if kwargs["model"] == "mistral-large-4":
                raise RuntimeError("504 gateway timeout")
            return _completion({"reply": "ok ?", "done": False})

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))
    res = client.post("/api/report/chat", json={"mode": "design_only", "messages": [{"role": "user", "content": "EDF"}]})
    assert res.status_code == 200
    assert seen_models[0] == "mistral-small-latest"  # Q&A rapide d'abord
    assert "mistral-large-4" not in seen_models  # done=false : pas d'appel de génération


def test_complete_json_model_fallback_on_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.routers.api.report.route import complete_json

    seen: list[str] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            seen.append(str(kwargs["model"]))
            if kwargs["model"] == "mistral-large-4":
                raise RuntimeError("504 gateway timeout")
            return _completion({"reply": "fallback ok"})

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))
    data = complete_json("system", "payload")
    assert data == {"reply": "fallback ok"}
    assert seen[0] == "mistral-large-4" and seen[-1] == "mistral-medium-latest"


def test_report_chat_survives_history_save_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.routers.api.report import chat as chat_module

    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(
        report_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(
                complete=lambda **kwargs: _completion({"reply": "voici", "done": True, "css": "body{}", "reportJson": None})
            )
        ),
    )

    def boom(**kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", "data")

    monkeypatch.setattr(chat_module._store, "save_entry", boom)
    res = client.post("/api/report/chat", json={"mode": "design_only", "messages": [{"role": "user", "content": "EDF"}]})
    assert res.status_code == 200
    assert res.json()["css"] == "body{}"
    assert res.json()["historyId"] is None


def test_report_chat_fetches_site_brand_when_url_given(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.routers.api.report import chat as chat_module

    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    captured: list[dict] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            captured.append(kwargs)
            return _completion({"reply": "Quelle URL ?", "done": False})

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))
    monkeypatch.setattr(
        chat_module,
        "fetch_site_brand",
        lambda url: {"url": url, "title": "Grandir", "colors": ["#ffcf00", "#123456"], "fonts": ["'Nunito', sans-serif"]},
    )
    res = client.post(
        "/api/report/chat",
        json={"mode": "design_only", "messages": [{"role": "user", "content": "Client Grandir, site https://www.grandir.com/fr/"}]},
    )
    assert res.status_code == 200
    payload = json.loads(captured[0]["messages"][1]["content"])
    assert payload["siteBrand"]["title"] == "Grandir"
    assert "#ffcf00" in payload["siteBrand"]["colors"]


def test_report_chat_skips_site_fetch_in_json_only_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.routers.api.report import chat as chat_module

    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    called = []
    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **k: _completion({"reply": "ok ?", "done": False}))))
    monkeypatch.setattr(chat_module, "fetch_site_brand", lambda url: called.append(url) or {})
    res = client.post(
        "/api/report/chat",
        json={"mode": "structure_only", "messages": [{"role": "user", "content": "site https://example.com"}]},
    )
    assert res.status_code == 200
    assert called == []


def test_report_chat_blocked_site_mentions_bot_protection(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.routers.api.report import chat as chat_module

    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **k: _completion({"reply": "ok ?", "done": False}))))
    monkeypatch.setattr(chat_module, "fetch_site_brand", lambda url: {"url": url, "blocked": True, "status": 403})
    res = client.post(
        "/api/report/chat",
        json={"mode": "design_only", "messages": [{"role": "user", "content": "site https://bloque.example"}]},
    )
    assert res.status_code == 200


def test_report_chat_passes_screenshot_image_to_model(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    captured: list[dict] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            captured.append(kwargs)
            return _completion({"reply": "ok ?", "done": False})

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))
    res = client.post(
        "/api/report/chat",
        json={"mode": "design_only", "messages": [{"role": "user", "content": "voici la capture"}], "imageB64": "aGVsbG8="},
    )
    assert res.status_code == 200
    content = captured[0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert any(part.get("type") == "image_url" and "aGVsbG8=" in part["image_url"]["url"] for part in content)


def test_xlsx_inline_strings_and_english_headers_are_parsed() -> None:
    import zipfile

    from api.routers.api.report.chat import (
        extract_organization_id,
        parse_csv_indicators,
        xlsx_to_csv_text,
    )

    def cell(ref: str, text: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    header = "".join(cell(f"{chr(65+i)}1", h) for i, h in enumerate(["ORGANIZATION ID", "THEME", "SUBTHEME", "TYPE", "INDICATOR", "PARENT ID"]))
    row2 = "".join(cell(f"{chr(65+i)}2", v) for i, v in enumerate(["49", "Environnement", "GES", "NUMBER", "Émissions GES", "412225"]))
    sheet = f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{header}</row><row r="2">{row2}</row></sheetData></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="DATA" sheetId="1" r:id="rIdSheet1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdSheet1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    text = xlsx_to_csv_text(buf.getvalue())
    assert "THEME" in text.splitlines()[0]
    indicators, errors = parse_csv_indicators(text)
    assert errors == []
    assert indicators[0]["name"] == "Émissions GES"
    assert indicators[0]["parentId"] == 412225
    assert extract_organization_id(text) == 49


def test_report_routes_require_gateway_token(client: TestClient) -> None:
    from utils.mistral import install_caller_credentials

    install_caller_credentials(None)  # no caller token on the request
    res = client.post("/api/report/chat", json={"mode": "design_only", "messages": []})
    assert res.status_code == 401
    res2 = client.get("/api/report/history")
    assert res2.status_code == 401


def test_blocked_site_forces_awaiting_file_button(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.routers.api.report import chat as chat_module

    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **k: _completion({"reply": "ok", "done": False}))))
    monkeypatch.setattr(chat_module, "fetch_site_brand", lambda url: {"url": url, "blocked": True, "status": 403})
    res = client.post(
        "/api/report/chat",
        json={"mode": "design_only", "messages": [{"role": "user", "content": "Decathlon https://www.decathlon.fr"}]},
    )
    body = res.json()
    assert body["awaitingFile"] is True
    assert "capture" in body["reply"].lower()


def test_bare_403_without_bot_markers_is_error_not_blocked() -> None:
    import httpx
    from api.routers.api.report.chat import fetch_site_brand

    def fake_get(url: str) -> httpx.Response:
        return httpx.Response(403, text="<html><body>Forbidden</body></html>", request=httpx.Request("GET", url))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: fake_get(url))
    out = fetch_site_brand("https://www.auchan.fr/")
    assert out.get("blocked") is not True
    assert "error" in out
    monkeypatch.undo()


def test_real_bot_wall_is_blocked() -> None:
    import httpx
    from api.routers.api.report.chat import fetch_site_brand

    def fake_get(url: str) -> httpx.Response:
        return httpx.Response(403, text="<html><title>Just a moment...</title>cloudflare</html>", request=httpx.Request("GET", url))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: fake_get(url))
    out = fetch_site_brand("https://bloque.example")
    assert out.get("blocked") is True
    monkeypatch.undo()


def test_parse_keeps_only_most_recent_exercise_per_indicator() -> None:
    from api.routers.api.report.chat import parse_csv_indicators

    csv_text = (
        "EXERCISE;THEME;INDICATOR;TYPE;PARENT ID\n"
        "2025;Env;Émissions GES 2025;Nombre;412225\n"
        "2026;Env;Émissions GES 2026;Nombre;412225\n"
        "2024;Env;Émissions GES 2024;Nombre;412225\n"
        "2026;Social;Effectif;Nombre;777\n"
    )
    indicators, errors = parse_csv_indicators(csv_text)
    assert errors == []
    assert len(indicators) == 2
    ges = next(i for i in indicators if i["parentId"] == 412225)
    assert ges["name"] == "Émissions GES 2026"


def test_fetch_site_brand_extracts_colors_and_fonts() -> None:
    import httpx
    from api.routers.api.report.chat import fetch_site_brand

    html = "<html><head><title>Client Demo</title><link rel='stylesheet' href='/style.css'><style>body{font-family:'Montserrat',sans-serif;color:#222222}</style></head><body style='color:#e2001a'>x</body></html>"
    css = ":root{--brand:#e2001a}h1{font-family:'Montserrat';color:#e2001a}"

    class FakeResp:
        def __init__(self, text: str, url: str, status: int = 200):
            self.text = text
            self.status_code = status
            self.url = httpx.URL(url)

    class FakeClient:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":  # noqa: PYI034  test double
            return self

        def __exit__(self, *a: object) -> None:
            pass

        def get(self, url: str, **k: object) -> FakeResp:
            if url.endswith(".css"):
                return FakeResp(css, url)
            return FakeResp(html, "https://client.example/")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    out = fetch_site_brand("https://client.example/")
    assert out["title"] == "Client Demo"
    assert "#e2001a" in out["colors"] and "#222222" in out["colors"]
    assert any("Montserrat" in f for f in out["fonts"])
    monkeypatch.undo()


def test_report_chat_last_resort_ml4_generation_on_persistent_announcements(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("REPORT_HISTORY_PATH", str(tmp_path / "history.json"))
    outputs = iter(
        [
            {"reply": "Construction du rapport JSON en cours...", "done": False},
            {"reply": "Toujours en cours...", "done": False},
            {"reply": "Toujours en cours...", "done": False},
            {"reply": "Voici le JSON final.", "done": True, "reportJson": {"blocks": [{"type": "header", "data": {"text": "E1", "level": 2}}]}},
        ]
    )
    seen_models: list[str] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            seen_models.append(str(kwargs["model"]))
            return _completion(next(outputs))

    monkeypatch.setattr(report_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))
    res = client.post(
        "/api/report/chat",
        json={"mode": "structure_only", "messages": [{"role": "user", "content": "voici le CSV"}], "csv": "THEME;INDICATOR;TYPE;PARENT ID\nEnv;GES;Nombre;1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["done"] is True
    assert body["reportJson"]["blocks"][0]["data"]["text"] == "E1"
    assert "mistral-large-4" in seen_models  # dernier recours bien passé sur ML4
