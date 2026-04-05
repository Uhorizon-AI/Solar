from .agent import AgentProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider

PROVIDERS = {
    "claude": ClaudeProvider(),
    "codex": CodexProvider(),
    "gemini": GeminiProvider(),
    "agent": AgentProvider(),
    "ollama": OllamaProvider(),
}

__all__ = [
    "PROVIDERS",
    "ClaudeProvider",
    "CodexProvider",
    "GeminiProvider",
    "AgentProvider",
    "OllamaProvider",
]
