"""Built-in GGUF catalog, hardware fit, import, and the pinned llama.cpp runtime."""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automoto import gguf_runtime, server, settings


@pytest.fixture(autouse=True)
def _reset():
    gguf_runtime.reset_for_tests()
    yield
    gguf_runtime.reset_for_tests()


def test_catalog_covers_the_named_families_and_refuses_full_kimi():
    families = {model.family for model in gguf_runtime.CATALOG}
    assert {"Kimi", "Qwen", "Llama", "Mistral", "Gemma", "DeepSeek", "Phi"} <= families
    full = gguf_runtime.by_id("kimi-k2")
    assert full is not None and not full.downloadable
    assert full.download_gb >= 600
    fit = gguf_runtime.assess(full, {"ram_gb": 64})
    assert fit["can_run"] is False and "624" in fit["reason"]


def test_a_small_pc_cannot_run_a_large_model_and_a_large_pc_can():
    small = {"ram_gb": 8.0, "gpu": None}
    view = gguf_runtime.recommend(small)
    by_name = {row["id"]: row for row in view["models"]}
    assert by_name["kimi-k2-distill-32b"]["can_run"] is False
    assert "32" in by_name["kimi-k2-distill-32b"]["reason"]
    assert by_name["qwen2.5-3b"]["can_run"] is True
    assert by_name["kimi-vl-a3b"]["can_run"] is False
    assert view["best"] == "qwen2.5-3b"
    big = gguf_runtime.recommend({"ram_gb": 64.0, "gpu": None})
    fitted = {row["id"]: row for row in big["models"]}
    assert fitted["kimi-vl-a3b"]["can_run"] is True
    assert fitted["kimi-k2"]["can_download"] is False
    assert big["best"] == "kimi-k2-distill-32b"


def test_low_disk_blocks_the_download():
    model = gguf_runtime.by_id("qwen2.5-7b")
    fit = gguf_runtime.assess(model, {"ram_gb": 32}, free_gb=1.0)
    assert fit["can_run"] is True and fit["can_download"] is False
    assert "disk" in fit["reason"]


def test_import_accepts_a_gguf_and_rejects_anything_else(tmp_path: Path):
    good = tmp_path / "My Model.gguf"
    good.write_bytes(b"GGUF" + b"\x00" * 64)
    saved = gguf_runtime.import_file(good)
    assert saved["id"].startswith("custom-")
    assert gguf_runtime.by_id("kimi-k2")  # catalog still intact
    copied = gguf_runtime._installed_path(saved["id"])
    assert copied is not None and copied.read_bytes().startswith(b"GGUF")
    bad = tmp_path / "notes.gguf"
    bad.write_bytes(b"not a model, just text that is long enough!!")
    with pytest.raises(ValueError, match="GGUF"):
        gguf_runtime.import_file(bad)
    with pytest.raises(ValueError, match="gguf"):
        gguf_runtime.import_file(tmp_path / "model.bin")


def test_delete_stays_inside_the_model_folder(tmp_path: Path):
    src = tmp_path / "keep.gguf"
    src.write_bytes(b"GGUF" + b"\x01" * 40)
    saved = gguf_runtime.import_file(src)
    gguf_runtime.use(saved["id"])
    assert settings.get("gguf_model") == saved["id"]
    gguf_runtime.delete(saved["id"])
    assert gguf_runtime._installed_path(saved["id"]) is None
    assert settings.get("gguf_model") is None
    outside = tmp_path / "secret.gguf"
    outside.write_bytes(b"GGUF" + b"\x02" * 40)
    with pytest.raises(ValueError):
        gguf_runtime.delete("../" + outside.name)


def test_engine_command_binds_loopback_only(tmp_path: Path):
    command = gguf_runtime.build_command(tmp_path / "llama-server", tmp_path / "m.gguf", 27123, 4096)
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in command


def test_runtime_rejects_a_bad_checksum_and_accepts_a_pinned_zip(monkeypatch, tmp_path: Path):
    payload = b"not-really-llama"
    monkeypatch.setattr(gguf_runtime, "_asset", lambda: ("engine.zip", "0" * 64))
    monkeypatch.setattr(gguf_runtime.urllib.request, "urlopen",
                        lambda *a, **k: _Body(payload))
    with pytest.raises(ValueError, match="checksum"):
        gguf_runtime.ensure_runtime()

    archive = io.BytesIO()
    binary_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"build/{binary_name}", b"#!/bin/sh\n")
    data = archive.getvalue()
    digest = __import__("hashlib").sha256(data).hexdigest()
    monkeypatch.setattr(gguf_runtime, "_asset", lambda: ("engine.zip", digest))
    monkeypatch.setattr(gguf_runtime.urllib.request, "urlopen", lambda *a, **k: _Body(data))
    info = gguf_runtime.ensure_runtime()
    assert info["installed"] is True
    assert gguf_runtime._find_binary(gguf_runtime.runtime_dir()) is not None


def test_archive_paths_cannot_escape(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(ValueError, match="unsafe"):
        gguf_runtime._safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_pull_refuses_a_model_the_machine_cannot_run(monkeypatch):
    monkeypatch.setattr(gguf_runtime, "_hw", lambda: {"ram_gb": 4.0})
    monkeypatch.setattr(gguf_runtime, "_free_gb", lambda: 100.0)
    with pytest.raises(ValueError, match="memory"):
        gguf_runtime.pull("llama-3.1-8b")


def test_help_and_import_endpoints():
    client = TestClient(server.app)
    headers = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    guide = client.get("/api/help", headers=headers).json()
    ids = {item["id"] for item in guide["settings"]}
    assert {"approval", "offline-only", "folders", "provider-order", "theme"} <= ids
    assert {item["id"] for item in guide["studios"]} >= {"document", "research", "developer"}
    assert guide["tools"] and all(tool["description"] for tool in guide["tools"])
    panel = client.get("/api/local", headers=headers).json()
    assert "Kimi" in {row["family"] for row in panel["gguf"]["models"]}
    src = gguf_runtime.models_dir().parent.parent / "sample.gguf"
    # models_dir is under the temp home; write beside it via import body
    sample = Path(gguf_runtime.models_dir().parent / "sample.gguf")
    sample.write_bytes(b"GGUF" + b"z" * 40)
    imported = client.post("/api/local/gguf/import", headers=headers, json={"path": str(sample)}).json()
    assert imported["id"].startswith("custom-")
    assert client.post("/api/local/gguf/import", headers=headers, json={"path": str(sample) + ".missing"}).status_code == 400
    used = client.post("/api/local/gguf/use", headers=headers, json={"id": imported["id"]})
    assert used.status_code == 200
    assert client.post("/api/local/gguf/delete", headers=headers, json={"id": imported["id"]}).json()["ok"] is True


def test_settings_reject_a_bad_gguf_id():
    with pytest.raises(settings.SettingsError):
        settings.update({"gguf_model": "../etc/passwd"})
    assert settings.update({"gguf_model": "qwen2.5-3b"})["gguf_model"] == "qwen2.5-3b"


class _Body:
    def __init__(self, data: bytes):
        self._data = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n: int) -> bytes:
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_status_json_is_serialisable():
    payload = gguf_runtime.catalog_view()
    json.dumps(payload)
