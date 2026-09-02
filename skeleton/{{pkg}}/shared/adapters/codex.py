"""Adapter for the OpenAI Codex CLI.

Codex emits a JSONL event stream with thread, agent-message, completion, usage, and error
events. Resume is the ``exec resume`` subcommand, which does not accept ``--sandbox``;
resumed calls set sandbox mode through configuration. Schema and resume are incompatible.
Schema is passed as a file path, while reasoning effort and approval policy are configuration
overrides. Inherited stdin is disabled by the shared runner.

The working directory may be a data directory rather than a Git repository, so the command
uses ``--skip-git-repo-check``. Omitting ``--model`` preserves the account default, while
model aliases belonging to another client are deliberately not forwarded. This vendored
implementation is owned by the generated repository and flags require live verification.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import Capabilities, HarnessAdapter, RunResult

_CLAUDE_ALIASES = {"sonnet", "opus", "haiku"}


def _claude_family(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith("claude") or normalized in _CLAUDE_ALIASES


class CodexAdapter(HarnessAdapter):
    name = "codex"

    def __init__(self, binary: str = "codex"):
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
        # Codex has no per-tool allowlist, so allowed_tools is intentionally ignored. Sandbox
        # mode defines the capability boundary.
        if resume_session_id and schema_path:
            raise ValueError("codex: schema and resume are incompatible; choose one")
        cmd = [self.binary, "exec"]
        if resume_session_id:
            cmd += ["resume", resume_session_id]
            sandbox = ["-c", "sandbox_mode=workspace-write"]
        else:
            sandbox = ["--sandbox", "workspace-write"]
        cmd += ["--json", "-c", "approval_policy=never", *sandbox]
        cmd += ["--skip-git-repo-check"]
        if model and not _claude_family(model):
            cmd += ["--model", model]
        if effort:
            cmd += ["-c", f"model_reasoning_effort={effort}"]
        if system_prompt_path:
            cmd += ["-c", f"model_instructions_file={system_prompt_path}"]
        if schema_path:
            schema = Path(schema_path).read_text("utf-8").strip()
            if not schema:
                raise ValueError(f"empty schema {schema_path}; refusing an unconstrained call")
            cmd += ["--output-schema", schema_path]
        cmd.append(prompt)
        return cmd

    def parse_output(self, stdout, exit_code) -> RunResult:
        """Parse JSONL, joining agent-message text and preserving structured failures.

        Agent-message content may be a list of blocks. A thread ID becomes the resumable
        session ID, usage remains in ``raw``, and malformed lines are skipped. When no valid
        JSON object exists, return a truthful failed result containing the raw output.
        """

        text_parts: list[str] = []
        usage = error_message = session_id = codex_error_info = None
        parsed_any = False
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            parsed_any = True
            event_type = event.get("type")
            if event_type == "thread.started":
                session_id = event.get("thread_id")
                continue
            item = event.get("item") if isinstance(event.get("item"), dict) else event
            if event.get("codex_error_info") or item.get("codex_error_info"):
                codex_error_info = event.get("codex_error_info") or item.get("codex_error_info")
            item_type = item.get("item_type") or item.get("type")
            if event_type == "item.completed" and item_type == "agent_message":
                text = item.get("text")
                if text is None:
                    text = item.get("content")
                if isinstance(text, list):
                    text = "".join(
                        block.get("text", "") for block in text if isinstance(block, dict))
                if text:
                    text_parts.append(str(text))
            elif event_type == "turn.completed":
                usage = event.get("usage")
            elif event_type == "error" or event.get("is_error"):
                error_message = str(event.get("message") or event.get("error") or "codex error")
        if not parsed_any:
            return RunResult(ok=False, text=stdout or "", exit_code=exit_code)
        ok = exit_code == 0 and error_message is None
        return RunResult(
            ok=ok,
            text="\n".join(text_parts),
            exit_code=exit_code,
            session_id=session_id,
            cost_usd=None,
            raw={
                "usage": usage,
                "error": error_message or "",
                "codex_error_info": codex_error_info or "",
            },
        )
