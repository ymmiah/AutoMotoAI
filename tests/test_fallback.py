"""Per-provider model fallback, retries with backoff, clear errors and `automoto doctor` (all mocked)."""

import pytest
from fastapi.testclient import TestClient

from automoto import doctor, providers, router, server
from automoto.providers import REGISTRY, ProviderError

ALL_KEYS = [k for p in REGISTRY.values() for k in p.env_keys]
NIM = REGISTRY["nim"]
GEM = REGISTRY["gemini"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ALL_KEYS + ["AI_PROVIDER", "NIM_MODEL", "NIM_AGENT_MODEL", "NIM_VISION_MODEL", "NIM_REVIEW_MODEL",
                         "GEMINI_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "auto")


def scripted(rules, log):
    """rules: {(provider, model) or provider: exception or callable(n)->exception|None}."""
    def t(spec, messages, model, key, **_):
        log.append((spec.id, model))
        rule = rules.get((spec.id, model), rules.get(spec.id))
        if callable(rule) and not isinstance(rule, Exception):
            rule = rule(sum(1 for x in log if x == (spec.id, model)))
        if rule:
            raise rule
        return f"hi from {spec.id}/{model}"
    return t


def e404(pid="nim"):
    return ProviderError(pid, "NotFoundError: Error code: 404 - 404 page not found", status=404)


# -- 404 / 410: next model of the same provider, remembered for an hour -------------------
def test_nim_404_falls_back_to_next_nim_model_and_is_remembered(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    first, second = NIM.all_models("text")[:2]
    log = []
    ans = router.ask("hello", transport=scripted({("nim", first): e404()}, log))
    assert ans.provider == "nim" and ans.model == second
    assert log == [("nim", first), ("nim", second)]
    assert providers.is_unavailable("nim", first)
    log.clear()
    router.ask("hello again", transport=scripted({}, log))
    assert log == [("nim", second)]  # the 404 model is skipped for the next hour


def test_unavailable_cache_expires(monkeypatch):
    providers.mark_unavailable("nim", "x/y", ttl=-1)
    assert not providers.is_unavailable("nim", "x/y")
    providers.mark_unavailable("nim", "x/y")
    assert providers.is_unavailable("nim", "x/y") and ("nim", "x/y") in providers.unavailable_models()


@pytest.mark.parametrize("exc", [
    ProviderError("nim", "Gone: model retired", status=410),
    ProviderError("nim", "BadRequestError: Function 'abc' not found for account", status=400),
    ProviderError("nim", "The model `foo` does not exist or you do not have access to it"),
])
def test_410_and_model_not_found_words_count_as_missing(monkeypatch, exc):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    first = NIM.all_models("text")[0]
    ans = router.ask("hello", transport=scripted({("nim", first): exc}, []))
    assert ans.provider == "nim" and ans.model != first and providers.is_unavailable("nim", first)


def test_bad_request_and_rate_limit_are_not_missing():
    assert not providers.model_missing(ProviderError("nim", "400 tools not supported", status=400))
    assert not providers.model_missing(ProviderError("nim", "429 too many requests", status=429))
    assert not providers.model_missing(ProviderError("nim", "403 forbidden", status=403))


def test_env_override_comes_first_then_fallbacks(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    monkeypatch.setenv("NIM_MODEL", "my/own-model")
    assert NIM.all_models("text")[0] == "my/own-model"
    log = []
    ans = router.ask("hello", transport=scripted({("nim", "my/own-model"): e404()}, log))
    assert log[0] == ("nim", "my/own-model") and ans.model == NIM.fallbacks["text"][0]


def test_every_provider_has_fallbacks_for_free_tiers():
    for pid in ("nim", "gemini", "groq", "openrouter"):
        spec = REGISTRY[pid]
        assert len(spec.all_models("text")) >= 3, pid
        assert len(spec.all_models("vision")) >= 2, pid
    assert "meta/llama-3.2-90b-vision-instruct" in NIM.all_models("vision")
    assert "openai/gpt-oss-20b" in NIM.all_models("agent")


def test_all_nim_models_404_message_lists_models_and_hints(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    with pytest.raises(router.AllProvidersFailed) as ei:
        router.ask("hello", transport=scripted({"nim": e404()}, []))
    msg = str(ei.value)
    assert "model not available to this key (404)" in msg
    for m in NIM.all_models("text")[:3]:
        assert m in msg
    assert "NIM_MODEL" in msg and "automoto doctor" in msg
    assert "GEMINI_API_KEY" in msg and "GROQ_API_KEY" in msg  # suggest a free backup key
    assert "test-n" not in msg
    # next request: everything is known-missing, so no network call at all
    log = []
    with pytest.raises(router.AllProvidersFailed) as ei:
        router.ask("hello", transport=scripted({}, log))
    assert log == [] and "skipped" in str(ei.value)


# -- 401 / 403: bad key ----------------------------------------------------------------
def test_403_stops_that_provider_and_says_get_a_new_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    log = []
    with pytest.raises(router.AllProvidersFailed) as ei:
        router.ask("hello", transport=scripted({"nim": ProviderError("nim", "PermissionDeniedError: 403", status=403)}, log))
    assert len(log) == 1  # no point trying the other models with a rejected key
    msg = str(ei.value)
    assert "key was rejected (403)" in msg and "build.nvidia.com" in msg and "NVIDIA_API_KEY" in msg
    assert NIM.all_models("text")[0] in msg
    assert not providers.is_unavailable("nim", NIM.all_models("text")[0])


# -- 503 / 5xx / 429 / timeouts: backoff retries, then another model ----------------------
def test_503_is_retried_with_backoff_then_next_gemini_model(monkeypatch, fast_retries):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    first, second = GEM.all_models("text")[:2]
    log = []
    busy = ProviderError("gemini", "InternalServerError: Error code: 503", status=503)
    ans = router.ask("hello", transport=scripted({("gemini", first): busy}, log))
    assert log == [("gemini", first)] * 3 + [("gemini", second)]
    assert ans.model == second and ans.tried[0]["attempts"] == 3
    assert len(fast_retries) == 2 and fast_retries[0] < fast_retries[1] <= router.MAX_WAIT_S  # exponential
    assert not providers.is_unavailable("gemini", first)  # busy is not "missing"


def test_transient_error_recovers_on_same_model(monkeypatch, fast_retries):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    first = GEM.all_models("text")[0]
    log = []
    flaky = lambda n: ProviderError("gemini", "503", status=503) if n == 1 else None  # noqa: E731
    ans = router.ask("hello", transport=scripted({("gemini", first): flaky}, log))
    assert ans.model == first and len(log) == 2 and len(fast_retries) == 1


def test_retry_after_is_honoured_and_long_waits_fail_over(monkeypatch, fast_retries):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    first = GEM.all_models("text")[0]
    calls = {"n": 0}

    def t(spec, messages, model, key, **_):
        if spec.id == "gemini" and model == first:
            calls["n"] += 1
            raise ProviderError("gemini", "429", status=429, retry_after=1.5 if calls["n"] == 1 else 60)
        return "ok"

    ans = router.ask("hello", prefer="gemini", transport=t)
    assert fast_retries == [1.5]  # Retry-After used as-is; a 60 s Retry-After is not waited for
    assert ans.provider == "nim"  # 429 = rate-limited key: next provider


def test_timeouts_and_5xx_are_transient_in_classify():
    class Resp:
        status_code = 503
        headers = {"retry-after": "2"}

    class Busy(Exception):
        response = Resp()

    class APITimeoutError(Exception):
        pass

    e = providers._classify("gemini", Busy("overloaded"))
    assert e.status == 503 and e.transient and e.retry_after == 2.0
    assert providers._classify("nim", APITimeoutError("Request timed out.")).transient
    assert not providers._classify("nim", ValueError("bad")).transient


def test_no_retries_when_disabled(monkeypatch, fast_retries):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("AUTOMOTO_RETRIES", "0")
    first = GEM.all_models("text")[0]
    log = []
    router.ask("hello", transport=scripted({("gemini", first): ProviderError("gemini", "503", status=503)}, log))
    assert log.count(("gemini", first)) == 1 and fast_retries == []


def test_retry_budget_caps_total_waiting(monkeypatch, fast_retries):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("AUTOMOTO_RETRY_BUDGET_S", "1")
    with pytest.raises(router.AllProvidersFailed):
        router.ask("hello", transport=scripted({"gemini": ProviderError("gemini", "503", status=503)}, []))
    assert sum(fast_retries) <= 1


def test_yasins_case_gemini_503_and_nim_404(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-g")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    rules = {"gemini": ProviderError("gemini", "InternalServerError: Error code: 503", status=503), "nim": e404()}
    log = []
    with pytest.raises(router.AllProvidersFailed) as ei:
        router.ask("hello", transport=scripted(rules, log))
    msg = str(ei.value)
    assert "503 = provider busy" in msg and "retried 2 times" in msg
    assert "model not available to this key (404)" in msg
    assert {m for p, m in log if p == "gemini"} >= set(GEM.all_models("text")[:2])  # other Gemini models tried
    assert {m for p, m in log if p == "nim"} == set(NIM.all_models("text"))


# -- agent turns -------------------------------------------------------------------------
def test_agent_native_404_retries_text_then_marks_and_moves_on(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    first, second = NIM.agent_models()[:2]
    log = []

    def t(spec, messages, model, key, *, tools, native, **_):
        log.append((model, native))
        if model == first:
            raise e404()
        return "done", []

    turn = router.ask_turn([{"role": "user", "content": "hi"}], [], known=set(), transport=t)
    assert log == [(first, True), (first, False), (second, True)]
    assert turn.model == second and providers.is_unavailable("nim", first)


def test_agent_503_retries_same_model(monkeypatch, fast_retries):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    n = {"c": 0}

    def t(spec, messages, model, key, *, tools, native, **_):
        n["c"] += 1
        if n["c"] < 3:
            raise ProviderError("nim", "503", status=503)
        return "done", []

    turn = router.ask_turn([{"role": "user", "content": "hi"}], [], known=set(), transport=t)
    assert turn.model == NIM.agent_models()[0] and len(fast_retries) == 2


# -- doctor --------------------------------------------------------------------------------
def test_doctor_probes_with_one_token_and_suggests_working_models(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    seen = []
    bad = {NIM.all_models("text")[0], NIM.all_models("agent")[0]}

    def t(spec, messages, model, key, **kw):
        seen.append(kw)
        if model in bad:
            raise e404()
        if model == "openai/gpt-oss-20b":
            raise ProviderError("nim", "empty response")  # 1 token of reasoning: still a working model
        return "o"

    rep = doctor.run(transport=t)
    assert all(k["max_tokens"] == 1 for k in seen)
    nim = rep["providers"][0]
    assert nim["key_ok"] is True and "openai/gpt-oss-20b" in nim["working"]
    states = {r["model"]: r["state"] for r in nim["models"]}
    assert all(states[m] == "missing" for m in bad)
    assert nim["suggest"]["NIM_MODEL"] == NIM.all_models("text")[1]
    assert nim["suggest"]["NIM_AGENT_MODEL"] == NIM.all_models("agent")[1]
    assert any("NIM_MODEL=" in h for h in rep["hints"]) and any("GEMINI_API_KEY" in h for h in rep["hints"])
    assert all(providers.is_unavailable("nim", m) for m in bad)
    assert "test-n" not in repr(rep)


def test_doctor_rejected_key_probes_once(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-n")
    calls = []

    def t(spec, messages, model, key, **kw):
        calls.append(model)
        raise ProviderError("nim", "403", status=403)

    rep = doctor.run(transport=t)
    assert len(calls) == 1 and rep["providers"][0]["key_ok"] is False
    assert any("build.nvidia.com" in h for h in rep["hints"])


def test_doctor_api_local_only(monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda keys=None, **k: {"providers": [], "hints": [], "configured": 0})
    c = TestClient(server.app)
    H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
    assert c.post("/api/doctor", json={}).status_code == 403
    r = c.post("/api/doctor", json={}, headers=H)
    assert r.status_code == 200 and r.json()["configured"] == 0
