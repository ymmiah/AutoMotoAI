"""Router tests - all HTTP is mocked, no real keys needed."""

import pytest

from automoto import providers, router
from automoto.providers import REGISTRY, ProviderError

ALL_KEYS = [k for p in REGISTRY.values() for k in p.env_keys]
IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ALL_KEYS + ["AI_PROVIDER", "DEFAULT_AI_PROVIDER"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")


def fake_transport(fail=(), log=None):
    def _t(spec, messages, model, key, **_):
        if log is not None:
            log.append((spec.id, model))
        assert key and key.startswith("test-")
        if spec.id in fail:
            raise ProviderError(spec.id, "429 rate limited", status=429)
        return f"hi from {spec.id}"
    return _t


def test_registry_shape_and_vision_flags():
    assert {"nim", "gemini", "groq", "openrouter", "openai", "claude"} <= set(REGISTRY)
    for p in REGISTRY.values():
        assert p.env_keys and p.text_model and isinstance(p.supports_vision, bool)
        if p.supports_vision:
            assert p.vision_model, f"{p.id} claims vision without a vision model"
    assert REGISTRY["nim"].supports_vision and "vision" in REGISTRY["nim"].vision_model
    assert "blackbox" not in REGISTRY
    assert len({p.priority for p in REGISTRY.values()}) == len(REGISTRY)


def test_no_keys_gives_clear_error():
    with pytest.raises(router.NoProviderError, match="No AI provider key"):
        router.ask("hello", transport=fake_transport())


def test_placeholder_keys_are_ignored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
    with pytest.raises(router.NoProviderError):
        router.ask("hello", transport=fake_transport())


def test_single_key_works(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    ans = router.ask("hello", transport=fake_transport())
    assert ans.provider == "gemini" and ans.text == "hi from gemini"
    assert ans.tried == [{"provider": "gemini", "model": ans.model, "ok": True, "ms": ans.tried[0]["ms"]}]


def test_failover_when_first_provider_raises(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    monkeypatch.setenv("GROQ_API_KEY", "test-q")
    log = []
    ans = router.ask("hello", prefer="nim", transport=fake_transport(fail={"nim"}, log=log))
    assert [p for p, _ in log] == ["nim", "groq"]
    assert ans.provider == "groq"
    assert ans.tried[0]["ok"] is False and ans.tried[0]["status"] == 429
    assert ans.tried[1]["ok"] is True


def test_generic_exception_still_fails_over(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")

    def t(spec, *a, **k):
        if spec.id == "nim":
            raise TimeoutError("boom")
        return "ok"

    assert router.ask("hello", prefer="nim", transport=t).provider == "gemini"


def test_all_fail_reports_every_attempt(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    with pytest.raises(router.AllProvidersFailed) as ei:
        router.ask("hello", transport=fake_transport(fail={"nim", "gemini"}))
    assert {t["provider"] for t in ei.value.tried} == {"nim", "gemini"}


def test_need_vision_skips_non_vision(monkeypatch):
    # Pretend Groq has no vision so we can prove it's skipped.
    monkeypatch.setitem(REGISTRY, "groq", REGISTRY["groq"].__class__(**{**REGISTRY["groq"].__dict__, "supports_vision": False}))
    monkeypatch.setenv("GROQ_API_KEY", "test-q")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    log = []
    ans = router.ask([{"role": "user", "content": [{"type": "text", "text": "what is this"}, IMG]}],
                     prefer="groq", transport=fake_transport(log=log))
    assert ans.provider == "nim" and ans.task == "vision"
    assert all(p != "groq" for p, _ in log)
    assert log[0][1] == REGISTRY["nim"].vision_model


def test_need_vision_without_vision_provider(monkeypatch):
    monkeypatch.setitem(REGISTRY, "groq", REGISTRY["groq"].__class__(**{**REGISTRY["groq"].__dict__, "supports_vision": False}))
    for pid in list(REGISTRY):
        if pid != "groq":
            monkeypatch.delitem(REGISTRY, pid)
    monkeypatch.setenv("GROQ_API_KEY", "test-q")
    with pytest.raises(router.NoProviderError, match="vision"):
        router.ask("describe", need_vision=True, transport=fake_transport())


def test_byok_override_keys(monkeypatch):
    ans = router.ask("hi", keys={"openrouter": "test-or"}, transport=fake_transport())
    assert ans.provider == "openrouter"


def test_task_heuristic():
    assert router.classify_task("what's on my screen?") == "vision"
    assert router.classify_task("fix this python traceback") == "code"
    assert router.classify_task("hey how are you") == "chat"
    assert router.classify_task("hi", has_image=True) == "vision"


def test_recommend_provider(monkeypatch):
    for k in ("NVIDIA_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "test-x")
    assert router.recommend_provider("quick hello") == "groq"         # fastest
    assert router.recommend_provider("refactor this python class") == "claude"  # strongest
    assert router.recommend_provider("read this screenshot") in {"claude", "nim", "groq"}
    assert router.recommend_provider("anything", only_configured=False) is not None


def test_code_task_uses_strong_model_then_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    log = []

    def t(spec, messages, model, key, **_):
        log.append(model)
        if model == REGISTRY["gemini"].strong_model:
            raise ProviderError(spec.id, "404 model not found", status=404)
        return "ok"

    ans = router.ask("debug this python stack trace", transport=t)
    assert log == [REGISTRY["gemini"].strong_model, REGISTRY["gemini"].text_model]
    assert ans.provider == "gemini" and ans.model == REGISTRY["gemini"].text_model


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("NIM_MODEL", "meta/custom")
    assert REGISTRY["nim"].model_for() == "meta/custom"


def test_status_never_contains_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-supersecret-123")
    assert "supersecret" not in repr(router.status())


def test_transport_wraps_sdk_errors(monkeypatch):
    class Boom(Exception):
        status_code = 503

    def bad(*a, **k):
        raise Boom("service unavailable")

    monkeypatch.setitem(providers.TRANSPORTS, "openai_compat", bad)
    with pytest.raises(ProviderError) as ei:
        providers.complete(REGISTRY["nim"], [{"role": "user", "content": "x"}], "m", "k")
    assert ei.value.status == 503 and ei.value.retryable


def test_anthropic_image_conversion():
    system, msgs = providers._to_anthropic([
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": [{"type": "text", "text": "what"}, IMG]},
    ])
    assert system == "be nice"
    assert msgs[0]["content"][1]["source"]["type"] == "base64"
