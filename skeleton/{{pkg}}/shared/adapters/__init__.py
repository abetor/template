"""Provider adapters behind one small interface.

Callers depend on ``HarnessAdapter`` and ``RunResult`` rather than client-specific event
formats. Adapter code is vendored into and owned by each generated repository.
"""

from .base import Capabilities, HarnessAdapter, RunResult, STOP_TO_EXIT
from .claude import ClaudeAdapter
from .codex import CodexAdapter

__all__ = [
    "Capabilities",
    "HarnessAdapter",
    "RunResult",
    "STOP_TO_EXIT",
    "ClaudeAdapter",
    "CodexAdapter",
]
