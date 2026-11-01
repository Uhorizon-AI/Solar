import json
import os
import re
import shlex

from cli_permissions import Finding, MCP_READ_TOOLS, MCP_SERVER, UNKNOWN
from .base import BaseProvider, SOLAR_WORKSPACE

# Antigravity treats -p/--print/--prompt as options that take the prompt as their
# value (unlike Claude/Cursor, where -p is a bare non-interactive switch).
_PRINT_FLAGS = frozenset({"-p", "--print", "--prompt"})


class AgyProvider(BaseProvider):
    """Antigravity CLI provider (`agy`).

    Command override: ``SOLAR_ROUTER_AGY_CMD``. Legacy ``*_GEMINI_CMD`` is not
    read — rename it; ``solar client doctor`` / ``upgrade`` warn if present.
    """

    name = "agy"
    # Antigravity is the successor of the Gemini CLI. Its ~/.gemini/settings.json carries no
    # permission rules, so static_permission_checks stays the base default (unknown).
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        # agy --help: --print takes the prompt as its value. Keep -p/--print out of
        # this template; get_cmd always appends --print <prompt> last so other flags
        # are never eaten as the prompt (see issue from measure-110: `-p took
        # "--dangerously-skip-permissions" as its prompt`).
        return f"agy --dangerously-skip-permissions --add-dir {SOLAR_WORKSPACE}"

    def get_cmd(self, prompt: str) -> list:
        """Build argv with the prompt bound to --print, never as a bare trailing arg.

        Strips any bare or ``=``-form -p/--print/--prompt from the env/default
        template (including a misplaced ``agy -p --dangerously-skip-permissions…``)
        and reattaches ``--print`` immediately before the real prompt.
        """
        new_key = f"SOLAR_ROUTER_{self.name.upper()}_CMD"
        old_key = f"SOLAR_AI_{self.name.upper()}_CMD"
        raw = (os.getenv(new_key) or os.getenv(old_key) or self.build_default_cmd()).strip()
        parts = shlex.split(raw)
        if not parts:
            raise RuntimeError(f"{new_key} is empty")
        out = [self.resolve_binary(parts[0])]
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok in _PRINT_FLAGS:
                i += 1
                if i < len(parts) and not parts[i].startswith("-"):
                    i += 1
                continue
            if tok.startswith(("-p=", "--print=", "--prompt=")):
                i += 1
                continue
            out.append(tok)
            i += 1
        out.extend(["--print", prompt])
        return out

    def ask_separator(self):
        # The prompt is the value of --print, so it can never be read as an option.
        return ["--print"]

    def read_only_args(self, cwd):
        return ["--mode", "plan", "--add-dir", str(cwd)], "--mode plan"

    def static_permission_checks(self, home, workspace):
        """No readable rules to judge, so `unknown`; the fix is what Antigravity's docs give.

        The `mcp(server/tool)` syntax comes from its permissions documentation and is not verified
        here (a third-party report says headless mode may ignore allow rules): the probe decides.
        """
        rules = [f"mcp({MCP_SERVER}/{tool})" for tool in MCP_READ_TOOLS]
        return [Finding(self.name, "mcp_read", UNKNOWN, "static",
                        "no readable permission rules; if the probe reports it blocked, the documented rule is below (unverified)",
                        setting="permissions.allow", file=str(home / ".gemini" / "antigravity-cli" / "settings.json"),
                        fix=f"add {', '.join(rules)} to permissions.allow",
                        snippet=json.dumps({"permissions": {"allow": rules}}, indent=2))]

    def clean_output(self, output: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        if (
            "Please visit the following URL to authorize the application" in cleaned
            or "Enter the authorization code:" in cleaned
        ):
            raise RuntimeError(
                "agy returned OAuth prompt in headless mode; "
                "run `agy auth login` (or equivalent) for non-interactive use"
            )
        if "Individual quota reached" in cleaned:
            raise RuntimeError(cleaned.strip())
        return cleaned
