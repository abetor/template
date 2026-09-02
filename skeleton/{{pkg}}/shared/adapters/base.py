"""Port LLM work through interchangeable subscription-backed CLI clients.

The minimum client contract is a headless one-shot process receiving a prompt and working
directory, a textual final result on stdout, and a distinguishable failure. Other features
are explicit capabilities; wrappers emulate missing features instead of claiming support.

Stop classification is centralized here. Subscription clients provide no machine-readable
quota query across providers, so classification uses carefully separated output patterns.
This vendored file is owned by each generated repository; change flags and patterns only
after direct verification.
"""
from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# The class boundary follows the remedy. An earlier implementation grouped HTTP 429 and
# "rate limit" with exhausted subscription quota. A concurrency burst then stopped an entire
# queue with exit 75 even though waiting seconds and retrying would have succeeded.
#
# _QUOTA means the subscription budget is exhausted and only the reset window, usually hours
# or days, can help. Signals refer to budget rather than request rate. The negative lookbehind
# below keeps "usage limit exceeded" in quota while excluding "rate limit exceeded".
_QUOTA = re.compile(
    r"usage limit|weekly limit|session limit|5-hour|out of credits|quota"
    r"|(?:hit|reached) your [^.\n]{0,24}limit"
    r"|(?<!rate[ -])\blimit (?:reached|exceeded)",
    re.I,
)

# _TRANSIENT means a retry after seconds or minutes may help. It includes request bursts,
# transport failures, and overloaded services. Client retries may already have happened, but
# another delayed retry is still preferable to treating the error as permanent. When a
# message contains both 429 and explicit usage-limit language, classify checks quota first.
_TRANSIENT = re.compile(
    r"\b(?:429|500|502|503|529)\b|too many requests|rate.?limit"
    r"|at capacity|try a different model|server[_ -]?overloaded|\boverloaded\b|timed?.?out|connection|"
    r"temporarily|try again|ECONNRESET|EAI_AGAIN",
    re.I,
)

# Shared mapping from stop class to CLI exit code.
STOP_TO_EXIT = {"done": 0, "quota": 75, "transient": 111, "fatal": 1}


@dataclass
class Capabilities:
    """Features a client supports natively; wrappers emulate the remainder."""

    json_events: bool
    schema_output: bool
    native_resume: bool
    subagents: bool
    mcp: bool


@dataclass
class RunResult:
    ok: bool
    text: str
    exit_code: int
    session_id: Optional[str] = None
    stop: str = "done"
    cost_usd: Optional[float] = None
    raw: dict = field(default_factory=dict)
    stderr: str = ""


class HarnessAdapter(ABC):
    """Client-specific command construction and output parsing with a shared runner."""

    name: str = "harness"

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def build_cmd(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        resume_session_id: Optional[str] = None,
        schema_path: Optional[str] = None,
        system_prompt_path: Optional[str] = None,
        allowed_tools: Optional[str] = None,
    ) -> list[str]: ...

    @abstractmethod
    def parse_output(self, stdout: str, exit_code: int) -> RunResult: ...

    def quota_patterns(self) -> Optional[re.Pattern]:
        """Return optional client-specific quota signals in addition to shared patterns."""

        return None

    def classify(self, result: RunResult) -> str:
        """Classify ``done``, ``quota``, ``transient``, or ``fatal`` in contract order.

        Quota is checked even for an otherwise successful exit because a client may return
        exit 0 with limit text. Quota also wins a mixed "429: usage limit reached" message.
        A successful result then becomes done before transient scanning, preventing either a
        client's recovered 429 or externally collected text about rate limits from turning a
        successful run into a retry. Finally, transient patterns apply to failed calls.

        Structured raw fields are part of the adapter contract: Claude supplies ``subtype``
        and ``api_error_status``; Codex supplies JSONL ``error`` and
        ``codex_error_info`` values.
        """

        blob = (
            f"{result.text}\n{result.stderr}\n{result.raw.get('subtype', '')}\n"
            f"{result.raw.get('api_error_status', '')}\n{result.raw.get('error', '')}\n"
            f"{result.raw.get('codex_error_info', '')}"
        )
        extra = self.quota_patterns()
        if _QUOTA.search(blob) or (extra and extra.search(blob)):
            return "quota"
        if result.ok:
            return "done"
        if _TRANSIENT.search(blob):
            return "transient"
        return "fatal"

    def run(
        self,
        prompt: str,
        *,
        cwd: str,
        timeout: Optional[float] = None,
        **build_kw,
    ) -> RunResult:
        """Run one client process; this is the only shared process-spawn location."""

        cmd = self.build_cmd(prompt, **build_kw)
        try:
            # DEVNULL prevents clients from reading inherited stdin until EOF and hanging with
            # a message such as "Reading additional input from stdin...".
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as error:
            out = error.stdout if isinstance(error.stdout, str) else ""
            return RunResult(
                ok=False, text=out, exit_code=-1, stderr="wall-timeout", stop="transient")
        result = self.parse_output(proc.stdout, proc.returncode)
        result.stderr = proc.stderr or ""
        result.stop = self.classify(result)
        if result.stop != "done":
            result.ok = False
        return result
