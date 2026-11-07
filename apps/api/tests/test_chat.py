from types import SimpleNamespace

import pytest
from api.routers.api.chat import route as chat_route
from fastapi.testclient import TestClient


def _completion(content: object) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def client() -> TestClient:
    from conftest import build_app

    return TestClient(build_app())


def test_chat_rejects_an_empty_conversation(client: TestClient) -> None:
    res = client.post("/api/chat", json={"messages": []})
    assert res.status_code == 422


def test_chat_rejects_a_malformed_message(client: TestClient) -> None:
    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": 42}]})
    assert res.status_code == 422


def test_chat_returns_the_reply_and_calls_mistral_small(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    class FakeChat:
        def complete(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return _completion("Bonjour !")

    monkeypatch.setattr(chat_route, "caller_mistral_client", lambda: SimpleNamespace(chat=FakeChat()))

    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Salut"}]})

    assert res.status_code == 200
    assert res.json() == {"reply": "Bonjour !"}
    assert calls == [
        {"model": "mistral-large-4", "messages": [{"role": "user", "content": "Salut"}]}
    ]


def test_chat_joins_text_chunks_when_content_is_not_a_plain_string(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = [
        SimpleNamespace(type="text", text="Bon"),
        SimpleNamespace(type="text", text="jour"),
        SimpleNamespace(type="image_url", image_url=None),
    ]
    monkeypatch.setattr(
        chat_route,
        "caller_mistral_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(complete=lambda **kwargs: _completion(chunks))),
    )

    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Salut"}]})

    assert res.status_code == 200
    assert res.json() == {"reply": "Bonjour"}
