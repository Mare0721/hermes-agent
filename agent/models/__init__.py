"""Model adapters for provider-specific wire protocols."""

from agent.models.vertex_ai import (
    AsyncVertexAIClient,
    VertexAIClient,
    build_vertex_client,
)

__all__ = [
    "AsyncVertexAIClient",
    "VertexAIClient",
    "build_vertex_client",
]
