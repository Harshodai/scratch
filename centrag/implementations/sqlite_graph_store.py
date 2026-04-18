"""
SQLite Graph Store — Production implementation of GraphStoreProtocol.

Provides a lightweight, zero-dependency knowledge graph for multi-tenant RAG.
Supports recursive traversal using SQLite CTEs (Common Table Expressions).

SOLID: Liskov Substitution — drop-in replacement for any GraphStore.
SOLID: Interface Segregation — specifically for relational triplet storage.
"""

from __future__ import annotations

import sqlite3

from centrag.abstractions.graph_store import Entity, Relation
from centrag.utils.logger import get_logger

logger = get_logger("implementations.graph.sqlite")


class SQLiteGraphStore:
    """
    Knowledge Graph stored in a local SQLite database.

    The WHY:
        Enterprise RAG often requires "connecting dots" across documents.
        While vector search is good at finding similar text, it fails at
        traversing relationships (e.g., "Find all companies that John Doe
        has invested in"). SQLite allows us to store these relationships
        locally with high performance and zero infrastructure management.
    """

    def __init__(self, base_path: str = "data"):
        import os

        self._db_path = os.path.join(base_path, "graph.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the SQLite connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row

        if not self._initialized:
            self._ensure_tables(conn)
            self._initialized = True

        return conn

    def _ensure_tables(self, conn: sqlite3.Connection):
        """Create the triplet and entity tables if they don't exist."""
        cursor = conn.cursor()

        # Triplets Table: (Subject, Predicate, Object)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS triplets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Entity Metadata Table (Optional but useful for search)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                name TEXT NOT NULL,
                team_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                entity_type TEXT DEFAULT 'general',
                metadata TEXT,
                PRIMARY KEY (name, team_id, namespace)
            )
        """)

        # Indices for performance and security
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_triplets_team_ns ON triplets (team_id, namespace)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_triplets_subject ON triplets (subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_triplets_object ON triplets (object)")

        conn.commit()

    async def add_triplets(self, team_id: str, namespace: str, triplets: list[Relation]) -> None:
        """Store a batch of knowledge triplets."""
        import json

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            for t in triplets:
                cursor.execute(
                    "INSERT INTO triplets (team_id, namespace, subject, "
                    "predicate, object, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                    (team_id, namespace, t.subject, t.predicate, t.object, json.dumps(t.metadata)),
                )

                # Also ensure entities are registered
                cursor.execute(
                    "INSERT OR IGNORE INTO entities (name, team_id, namespace) VALUES (?, ?, ?)",
                    (t.subject, team_id, namespace),
                )
                cursor.execute(
                    "INSERT OR IGNORE INTO entities (name, team_id, namespace) VALUES (?, ?, ?)",
                    (t.object, team_id, namespace),
                )

            conn.commit()
            logger.info("triplets_added", count=len(triplets), team_id=team_id)
        except Exception as e:
            conn.rollback()
            logger.error("triplets_insert_failed", error=str(e))
            raise e
        finally:
            conn.close()

    async def get_neighbors(self, team_id: str, namespace: str, entity_name: str, depth: int = 1) -> list[Relation]:
        """
        Find all relations connected to an entity up to a certain depth.
        Uses recursive CTE for depth traversal.
        """
        import json

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Recursive CTE to find neighbors
            # For depth=1, we don't really need a CTE but it's cleaner to support higher depths
            query = """
            WITH RECURSIVE neighbors(subject, predicate, object, current_depth) AS (
                -- Base case: find direct relations
                SELECT subject, predicate, object, 1
                FROM triplets
                WHERE team_id = ? AND namespace = ? AND (subject = ? OR object = ?)
                
                UNION
                
                -- Recursive step: find and join neighbors
                SELECT t.subject, t.predicate, t.object, n.current_depth + 1
                FROM triplets t
                JOIN neighbors n ON (
                    t.subject = n.object OR t.object = n.subject OR 
                    t.subject = n.subject OR t.object = n.object
                )
                WHERE t.team_id = ? AND t.namespace = ? AND n.current_depth < ?
            )
            SELECT DISTINCT * FROM neighbors
            """

            cursor.execute(query, (team_id, namespace, entity_name, entity_name, team_id, namespace, depth))
            rows = cursor.fetchall()

            results = [
                Relation(
                    subject=row["subject"],
                    predicate=row["predicate"],
                    object=row["object"],
                    metadata=json.loads(row.get("metadata", "{}")) if "metadata" in row else {},
                )
                for row in rows
            ]
            return results
        finally:
            conn.close()

    async def search_entities(self, team_id: str, namespace: str, query: str, limit: int = 5) -> list[Entity]:
        """Simple keyword search for entities."""
        import json

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM entities WHERE team_id = ? AND namespace = ? AND name LIKE ? LIMIT ?",
                (team_id, namespace, f"%{query}%", limit),
            )
            rows = cursor.fetchall()

            return [
                Entity(
                    name=row["name"],
                    entity_type=row["entity_type"],
                    metadata=json.loads(row.get("metadata", "{}")) if row["metadata"] else {},
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def delete_namespace(self, team_id: str, namespace: str) -> None:
        """Clear all data for a namespace."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM triplets WHERE team_id = ? AND namespace = ?", (team_id, namespace))
            cursor.execute("DELETE FROM entities WHERE team_id = ? AND namespace = ?", (team_id, namespace))
            conn.commit()
        finally:
            conn.close()
