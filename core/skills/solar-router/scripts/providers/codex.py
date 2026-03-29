import os
import shlex
import subprocess

from .base import BaseProvider, REPO_ROOT

# NOTE: codex CLI only works in interactive TUI mode.
# In non-interactive mode (stdin not a terminal) it will fail and the router
# will fall back to the next provider in priority order.


class CodexProvider(BaseProvider):
    name = "codex"

    def build_default_cmd(self) -> str:
        return f"codex --dangerously-bypass-approvals-and-sandbox"

    def stream(self, prompt: str):
        """Codex does not support non-interactive streaming. Falls back to run()."""
        yield self.run(prompt)
