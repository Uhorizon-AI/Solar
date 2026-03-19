import pathlib
import re
from typing import Dict

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_cmd = "gemini -y -p"

    def prepare_env(self, base_env: Dict[str, str]) -> Dict[str, str]:
        env = base_env.copy()
        env.setdefault("GEMINI_CLI_HOME", str(pathlib.Path.home()))
        env.setdefault("GEMINI_FORCE_ENCRYPTED_FILE_STORAGE", "false")
        return env

    def clean_output(self, output: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        if (
            "Please visit the following URL to authorize the application" in cleaned
            or "Enter the authorization code:" in cleaned
        ):
            raise RuntimeError(
                "gemini returned OAuth prompt in headless mode; "
                "credentials are not usable for non-interactive execution"
            )
        return cleaned
