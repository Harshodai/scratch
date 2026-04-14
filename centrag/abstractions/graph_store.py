from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Entity:
    """A node in the knowledge graph."""

    name: str
    entity_type: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Relation:
    """An edge in the knowledge graph."""

    subject: str
    predicate: str
    object: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GraphStoreProtocol(Protocol):
    """
    Protocol for knowledge graph storage.
    
    The WHY:
        Allows connecting disparate facts across documents that vector 
        similarity alone might miss. By abstracting the storage, we can
        start with a local SQLite implementation and scale to Neo4j/Memgraph
        without changing the extraction or retrieval logic.
    """

    @abstractmethod
    async def add_triplets(self, team_id: str, namespace: str, triplets: list[Relation]) -> None:
        """Add a batch of triplets to the graph."""
        ...

    @abstractmethod
    async def get_neighbors(self, team_id: str, namespace: str, entity_name: str, depth: int = 1) -> list[Relation]:
        """Find relations connected to a specific entity."""
        ...

    @abstractmethod
    async def search_entities(self, team_id: str, namespace: str, query: str, limit: int = 5) -> list[Entity]:
        """Find entities matching a keyword/semantic query."""
        ...

    @abstractmethod
    async def delete_namespace(self, team_id: str, namespace: str) -> None:
        """Clear all graph data for a specific namespace."""
        ...
