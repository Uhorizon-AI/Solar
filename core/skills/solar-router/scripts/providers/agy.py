import re

from .base import BaseProvider, SOLAR_WORKSPACE


class AgyProvider(BaseProvider):
    """Antigravity CLI provider (`agy`).

    Command override: ``SOLAR_ROUTER_AGY_CMD``. Legacy ``*_GEMINI_CMD`` is not
    read — rename it; ``solar client doctor`` / ``upgrade`` warn if present.
    """

    name = "agy"
    last_usage: dict | None = None

    def build_default_cmd(self) -> str:
        # agy --help: -p/--print = non-interactive; --dangerously-skip-permissions
        # auto-approves tools; --add-dir anchors workspace.
        return (
            f"agy -p --dangerously-skip-permissions --add-dir {SOLAR_WORKSPACE}"
        )

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
