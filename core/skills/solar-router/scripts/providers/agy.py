import json
import re

from cli_permissions import Finding, MCP_READ_TOOLS, MCP_SERVER, UNKNOWN
from .base import BaseProvider, SOLAR_WORKSPACE


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
        # agy --help: -p/--print = non-interactive; --dangerously-skip-permissions
        # auto-approves tools; --add-dir anchors workspace.
        return (
            f"agy -p --dangerously-skip-permissions --add-dir {SOLAR_WORKSPACE}"
        )

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
