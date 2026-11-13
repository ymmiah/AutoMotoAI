"""llama.cpp settings for the computer in front of the user."""

import time

from automoto import gguf_runtime
from automoto.offline_tune import choose_asset_key, command_flags, physical_threads, tune


def test_threads_follow_physical_cores_and_a_16gb_cpu_stays_responsive():
    spec = tune({"ram_gb": 15.6, "cpus": 8, "physical_cores": 4, "gpu": None, "isa": "avx2"})
    assert physical_threads(spec and {"cpus": 8, "physical_cores": 4}) == 4
    assert spec["threads"] == 4
    assert spec["context"] == 8192
    assert spec["batch"] == 512 and spec["ubatch"] == 256
    assert spec["mmap"] is True and spec["flash_attn"] is True
    assert spec["kv_type"] == "q8_0"
    assert spec["gpu_layers"] == 0
    assert spec["backend"] == "cpu-avx2"
    flags = command_flags(spec)
    assert flags[flags.index("-t") + 1] == "4"
    assert "--mmap" in flags and "-fa" in flags and "q8_0" in flags
    assert "-ngl" not in flags


def test_gpu_build_is_chosen_when_one_is_published():
    cuda = tune({"ram_gb": 16, "cpus": 8, "physical_cores": 4,
                 "gpu": {"name": "RTX", "vram_gb": 8, "kind": "nvidia"}, "isa": "avx2"})
    assert cuda["backend"] == "cuda" and cuda["gpu_layers"] == 999
    apple = tune({"ram_gb": 16, "cpus": 8, "physical_cores": 8, "gpu": {"kind": "apple"}, "isa": "neon"})
    assert apple["backend"] == "metal"
    assets = {
        ("win32", "AMD64"): ("cpu.zip", "aa"),
        ("win32", "AMD64", "cuda"): ("cuda.zip", "bb"),
        ("win32", "AMD64", "cpu-avx2"): ("avx.zip", "cc"),
    }
    assert choose_asset_key("win32", "AMD64", cuda, assets) == ("win32", "AMD64", "cuda")
    cpu = tune({"ram_gb": 16, "cpus": 8, "physical_cores": 4, "gpu": None, "isa": "avx2"})
    assert choose_asset_key("win32", "AMD64", cpu, assets) == ("win32", "AMD64", "cpu-avx2")
    assert choose_asset_key("linux", "x86_64", cpu, assets) == ("linux", "x86_64")


def test_engine_command_keeps_loopback_and_adds_the_tuned_flags(tmp_path):
    spec = tune({"ram_gb": 16, "cpus": 8, "physical_cores": 4,
                 "gpu": {"vram_gb": 8, "kind": "nvidia"}, "isa": "avx2"})
    cpu_cmd = gguf_runtime.build_command(tmp_path / "llama-server", tmp_path / "m.gguf", 27123, 4096, spec=spec)
    assert cpu_cmd[cpu_cmd.index("--host") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in cpu_cmd
    assert "-ngl" not in cpu_cmd
    assert cpu_cmd[cpu_cmd.index("-c") + 1] == "4096"
    assert "--mmap" in cpu_cmd and "-fa" in cpu_cmd
    gpu_cmd = gguf_runtime.build_command(tmp_path / "cuda" / "llama-server", tmp_path / "m.gguf", 27123, 8192, spec=spec)
    assert gpu_cmd[gpu_cmd.index("-ngl") + 1] == "999"


def test_sse_tokens_and_idle_unload(monkeypatch):
    assert gguf_runtime.token_from_sse('data: {"choices":[{"delta":{"content":"Hi"}}]}') == "Hi"
    assert gguf_runtime.token_from_sse("data: [DONE]") is None
    assert gguf_runtime.token_from_sse("data: {") is None

    class Proc:
        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            self.stopped = True
            return 0

        def kill(self):
            self.stopped = True

        stopped = False

    monkeypatch.setenv("AUTOMOTO_LLAMA_IDLE_S", "30")
    proc = Proc()
    gguf_runtime._PROC = proc
    gguf_runtime._LAST_USED = time.monotonic()
    assert gguf_runtime.unload_if_idle() is False
    gguf_runtime._LAST_USED = time.monotonic() - 120
    assert gguf_runtime.unload_if_idle() is True
    assert proc.stopped is True
    gguf_runtime.cancel_generation()
    assert gguf_runtime.generation_cancelled() is True
    gguf_runtime.reset_for_tests()


def test_catalog_marks_the_model_that_fits():
    view = gguf_runtime.recommend({"ram_gb": 8.0, "cpus": 4, "physical_cores": 2, "gpu": None, "isa": "avx2"})
    assert view["best"] == "qwen2.5-3b"
    shown = gguf_runtime.catalog_view()
    assert shown["tune"]["threads"] >= 1
    assert shown["tune"]["mmap"] is True
    marked = [row["id"] for row in shown["models"] if row.get("recommended")]
    assert marked == [shown["best"]]
