from .base import BaseProvider, REPO_ROOT


class AgentProvider(BaseProvider):
    name = "agent"

    def build_default_cmd(self) -> str:
        return f"agent -p -f --approve-mcps --workspace {REPO_ROOT}"
