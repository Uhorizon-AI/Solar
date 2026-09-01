from .agent import AgentProvider
from .agy import AgyProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .ollama import OllamaProvider

PROVIDERS = {
    "claude": ClaudeProvider(),
    "codex": CodexProvider(),
    "agy": AgyProvider(),
    "agent": AgentProvider(),
    "ollama": OllamaProvider(),
}

__all__ = [
    "PROVIDERS",
    "ClaudeProvider",
    "CodexProvider",
    "AgyProvider",
    "AgentProvider",
    "OllamaProvider",
]
