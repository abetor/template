"""Lock both sides of the quota/transient boundary in skeleton adapters.

Adapters are scaffolding rather than code executed directly by this repository. Tests load
the stamped module from a generated child built from the Git index, thereby exercising the
exact code delivered to tools. The rule travels through tracked ``<pkg>/shared/**`` files
while its regression gate remains centralized here.

The classification boundary comes from an observed failure where a burst HTTP 429 was
mistaken for exhausted quota and exit 75 stopped a queue. Intentionally exhausting a live
subscription would waste a quota window, so quota forms are synthetic and follow client
documentation. Capacity patterns reproduce observed task-completion messages.
"""
import importlib.util
import json
import sys

import pytest

from tooltemplate.cli import main


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    fixture_root = tmp_path_factory.mktemp("born")
    into = fixture_root / "tool-x"
    # This module fixture starts before the function-scoped autouse fixture, so isolate HOME
    # here as well to keep birth out of user storage.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HOME", str(fixture_root / "home"))
    monkeypatch.delenv("TOOLS_DATA", raising=False)
    (fixture_root / "home").mkdir()
    try:
        assert main(["birth", "--name", "tool-x", "--into", str(into)]) == 0
    finally:
        monkeypatch.undo()
    path = into / "tool_x" / "shared" / "adapters" / "base.py"
    spec = importlib.util.spec_from_file_location("born_shared_adapters.base", path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec because dataclasses with postponed annotations resolve through
    # sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def codex(base):
    """Load the real CodexAdapter from the same generated child."""
    path = base.__file__.replace("base.py", "codex.py")
    spec = importlib.util.spec_from_file_location("born_shared_adapters.codex", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def ad(base):
    """Minimal adapter exercising shared classification without client-specific logic."""
    class _Ad(base.HarnessAdapter):
        name = "test"

        def capabilities(self):
            return base.Capabilities(False, False, False, False, False)

        def build_cmd(self, prompt, **kw):
            return ["true"]

        def parse_output(self, stdout, exit_code):
            return base.RunResult(ok=exit_code == 0, text=stdout, exit_code=exit_code)

    return _Ad()


@pytest.mark.parametrize("msg", [
    "usage limit reached",                                 # shared form
    "You've hit your weekly limit - resets Mon 12:00am",   # weekly window
    "You've hit your usage limit. Try again in 4 hours.",  # specific quota beats try-again
    "5-hour limit reached, resets at 6pm",                 # session window
    "You have hit your limit",                             # short form
    "you are out of credits",                              # credit exhaustion
    "monthly quota exhausted",
    "429: usage limit reached",                            # mixed form resolves to quota
])
def test_classify_real_quota(ad, base, msg):
    """Exhausted subscription budget requires waiting for reset and exits 75.

    Explicit usage-budget text wins over generic HTTP 429 because unnecessary waiting is
    safer than repeatedly calling a genuinely exhausted quota.
    """
    assert ad.classify(base.RunResult(ok=False, text=msg, exit_code=1)) == "quota"
    assert ad.classify(base.RunResult(ok=False, text="", exit_code=1, stderr=msg)) == "quota"


@pytest.mark.parametrize("msg", [
    "429",                                                    # bare burst code
    "stream error: unexpected status 429 Too Many Requests",  # stream form
    "too many requests, please try again later",
    "Rate limit reached for gpt-5.4",                         # generic throttling form
    "rate limit exceeded",
    "you are being rate-limited",
])
def test_classify_burst_rate_limit_is_transient(ad, base, msg):
    """Burst throttling is transient and can be retried after seconds with exit 111.

    Moving 429 or rate-limit patterns back into quota must fail exactly these parameters.
    """
    assert ad.classify(base.RunResult(ok=False, text=msg, exit_code=1)) == "transient"
    assert ad.classify(base.RunResult(ok=False, text="", exit_code=1, stderr=msg)) == "transient"


def test_classify_codex_at_capacity_message_is_transient(ad, base):
    """An observed task-complete capacity message is transient, not fatal."""
    msg = "Selected model is at capacity. Please try a different model."
    assert ad.classify(base.RunResult(ok=False, text=msg, exit_code=1)) == "transient"


def test_classify_codex_try_different_model_alone_is_transient(ad, base):
    """The independent third form is not masked by an ``at capacity`` phrase."""
    assert ad.classify(base.RunResult(
        ok=False, text="Please try a different model.", exit_code=1)) == "transient"


def test_classify_codex_server_overloaded_from_parsed_error_info(codex):
    """A structured code travels through parse_output, raw fields, and classify."""
    adapter = codex.CodexAdapter()
    stdout = json.dumps({"type": "task_complete", "codex_error_info": "server_overloaded"})
    result = adapter.parse_output(stdout, exit_code=1)
    assert result.raw["codex_error_info"] == "server_overloaded"
    assert result.text == ""
    assert adapter.classify(result) == "transient"


def test_classify_quota_wins_even_on_ok_output(ad, base):
    """Quota is checked before the successful-result short circuit.

    A client may return exit 0 with limit text, which must not silently continue.
    """
    r = base.RunResult(ok=True, text="You have hit your usage limit, resets at 6pm",
                       exit_code=0)
    assert ad.classify(r) == "quota"


def test_classify_throttle_on_ok_run_stays_done(ad, base):
    """A successful 429 mention stays done after client retry or in collected text."""
    r = base.RunResult(ok=True, text="source explains 429 Too Many Requests and rate limit",
                       exit_code=0)
    assert ad.classify(r) == "done"


def test_stop_to_exit_makes_the_difference_visible(base):
    """Exit 75 stops a queue while 111 retries, making classification observable."""
    assert base.STOP_TO_EXIT["quota"] == 75
    assert base.STOP_TO_EXIT["transient"] == 111
