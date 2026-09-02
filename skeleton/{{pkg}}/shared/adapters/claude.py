"""Adapter for the Claude Code CLI.

``claude -p --output-format json [...] -- prompt`` returns one JSON object containing
``result``, ``session_id``, ``total_cost_usd``, ``is_error``, and subtype fields.

Verified constraints: schema content is passed inline, ``--`` protects the positional prompt
from greedy tool-list parsing, and resume uses ``--resume <session_id>``. The default tool
allowlist enforces read-only operation for an unattended process. This vendored implementation
is owned by the generated repository and client flags require live verification before change.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import Capabilities, HarnessAdapter, RunResult

# Web and read capabilities are allowed, while project writes are physically unavailable.
# A writing caller must pass its own explicit allowed-tools list.
READ_ONLY_TOOLS = "WebSearch WebFetch Read Grep Glob LS"


class ClaudeAdapter(HarnessAdapter):
    name = "claude"

    def __init__(self, binary: str = "claude"):
        self.binary = binary

    def capabilities(self) -> Capabilities:
        return Capabilities(
            json_events=True,
            schema_output=True,
            native_resume=True,
            subagents=True,
            mcp=True,
        )

    def build_cmd(
        self,
        prompt,
        *,
        model=None,
        effort=None,
        resume_session_id=None,
        schema_path=None,
        system_prompt_path=None,
        allowed_tools=None,
    ):
        cmd = [self.binary, "-p", "--output-format", "json", "--permission-mode", "default"]
        if model:
            cmd += ["--model", model]
        # In non-interactive default mode, tools outside this allowlist cannot ask for access.
        cmd += ["--allowedTools", allowed_tools or READ_ONLY_TOOLS]
        if effort:
            cmd += ["--effort", effort]
        if system_prompt_path:
            # Append a dedicated system-prompt file without replacing project instructions.
            cmd += ["--append-system-prompt-file", system_prompt_path]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        if schema_path:
            schema = Path(schema_path).read_text("utf-8").strip()
            if not schema:
                raise ValueError(f"empty schema {schema_path}; refusing an unconstrained call")
            cmd += ["--json-schema", schema]  # Claude expects inline content, not a path.
        cmd += ["--", prompt]
        return cmd

    def parse_output(self, stdout, exit_code) -> RunResult:
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            # Preserve non-JSON output from a pre-format crash instead of hiding it.
            return RunResult(
                ok=exit_code == 0 and bool(stdout.strip()), text=stdout, exit_code=exit_code)
        ok = exit_code == 0 and not data.get("is_error", False)
        return RunResult(
            ok=ok,
            text=data.get("result") or "",
            exit_code=exit_code,
            session_id=data.get("session_id"),
            cost_usd=data.get("total_cost_usd"),
            raw=data,
        )

    def quota_patterns(self) -> re.Pattern:
        # Observed subtype and text forms for subscription or API quota exhaustion.
        return re.compile(r"error_max_turns|resets at|upgrade to|claude usage", re.I)
