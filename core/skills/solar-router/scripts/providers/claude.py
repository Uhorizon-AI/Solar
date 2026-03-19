from .base import BaseProvider


class ClaudeProvider(BaseProvider):
    name = "claude"
    default_cmd = "claude -p --permission-mode bypassPermissions --no-session-persistence"
