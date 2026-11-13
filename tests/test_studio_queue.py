"""Studio task queue: order, cancel, reorder, and the list surviving a fresh read."""

import pytest
from fastapi.testclient import TestClient

from automoto import server, studio_queue


AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}


@pytest.fixture()
def client():
    return TestClient(server.app)


def test_queue_runs_one_then_the_next_and_survives_a_reload():
    first = studio_queue.enqueue("documents", "Write the summary")
    second = studio_queue.enqueue("research", "Check the sources")
    third = studio_queue.enqueue("visual", "Export the poster")
    assert [job["title"] for job in studio_queue.jobs()] == [
        "Write the summary", "Check the sources", "Export the poster"]
    assert first["status"] == "running"
    assert second["status"] == "queued" and third["status"] == "queued"
    moved = studio_queue.reorder(third["id"], "up")
    assert [job["title"] for job in moved if job["status"] != "cancelled"] == [
        "Write the summary", "Export the poster", "Check the sources"]
    studio_queue.reset_for_tests()
    again = studio_queue.jobs()
    assert again[0]["status"] == "running"
    assert again[0]["studio"] == "documents"
    assert [job["title"] for job in again] == [
        "Write the summary", "Export the poster", "Check the sources"]
    cancelled = studio_queue.cancel(again[2]["id"])
    assert cancelled[2]["status"] == "cancelled"
    finished = studio_queue.finish(again[0]["id"], ok=True, progress="Done")
    assert finished[0]["status"] == "done"
    assert finished[1]["status"] == "running"
    assert finished[1]["title"] == "Export the poster"


def test_cancel_a_running_task_starts_the_queued_one():
    running = studio_queue.enqueue("spreadsheets", "Recalculate")
    waiting = studio_queue.enqueue("developer", "Review the project")
    rows = studio_queue.cancel(running["id"])
    assert rows[0]["status"] == "cancelled"
    assert rows[1]["id"] == waiting["id"] and rows[1]["status"] == "running"


def test_queue_http_round_trip(client):
    created = client.post("/api/studio-queue", headers=AUTH,
                          json={"studio": "documents", "title": "Proofread"})
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "running"
    listed = client.get("/api/studio-queue", headers=AUTH)
    assert listed.json()["jobs"][0]["title"] == "Proofread"
    refused = client.post("/api/studio-queue", headers=AUTH, json={"studio": "nope", "title": "x"})
    assert refused.status_code == 400


def test_document_review_uses_the_builtin_engine_when_offline(client, monkeypatch):
    from automoto import document_ai, local_llm

    monkeypatch.setattr(local_llm, "offline", lambda: True)
    monkeypatch.setattr(document_ai, "_loopback_ollama", lambda: (_ for _ in ()).throw(AssertionError("ollama")))
    monkeypatch.setattr(document_ai, "_selected_model", lambda: (_ for _ in ()).throw(AssertionError("ollama model")))

    def ready_model():
        return "qwen2.5-3b"

    monkeypatch.setattr("automoto.offline_review.builtin_model", ready_model)
    monkeypatch.setattr("automoto.offline_review.complete_json",
                        lambda messages, **kwargs: {"proposal": "Clearer wording.", "explanation": "Shorter."})
    text = "The data were presented in the report."
    import hashlib
    body = {"mode": "rewrite", "markdown": text, "start": 0, "end": len(text),
            "sha256": hashlib.sha256(text.encode()).hexdigest()}
    response = client.post("/api/documents/ai/review", headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider"] == "llama.cpp"
    assert data["model"] == "qwen2.5-3b"
    assert data["proposal"] == "Clearer wording."
    assert data["applied"] is False
