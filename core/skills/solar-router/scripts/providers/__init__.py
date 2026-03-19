from .agent import AgentProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .gemini import GeminiProvider

PROVIDERS = {
    "claude": ClaudeProvider(),
    "codex": CodexProvider(),
    "gemini": GeminiProvider(),
    "agent": AgentProvider(),
}

__all__ = ["PROVIDERS", "ClaudeProvider", "CodexProvider", "GeminiProvider", "AgentProvider"]
