import pathlib

from .base import BaseProvider, REPO_ROOT

_CODEX_STATE_DIR = pathlib.Path.home() / ".codex"


class CodexProvider(BaseProvider):
    name = "codex"

    def build_default_cmd(self) -> str:
        return (
            f"codex exec --skip-git-repo-check --full-auto -C {REPO_ROOT} "
            f"--add-dir {_CODEX_STATE_DIR} --"
        )
