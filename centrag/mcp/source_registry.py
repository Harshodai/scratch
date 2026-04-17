"""
MCP Source Registry — Decoupled connection management with factory pattern.

The WHY:
    STOLEN from googleapis/mcp-toolbox ``internal/sources/sources.go``.

    The Toolbox separates Sources (database connections) from Tools (actions).
    This is architecturally cleaner than our old approach where
    ``DynamicSQLMCPFactory.create_server()`` coupled connection creation
    with tool generation in a single call.

    Key insight from the Go codebase:
    - ``SourceConfig`` is the *declaration* (what you write in YAML).
    - ``Source`` is the *initialized resource* (the live connection pool).
    - A *registry* maps type strings → factory functions (``init()`` auto-registration).

    We adapt this to Python using a class-based registry with Protocol typing.

Pattern: STRATEGY + REGISTRY (from Toolbox ``sources.Register()``)
SOLID: OCP — add new source types without modifying existing ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional, Protocol, runtime_checkable

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from centrag.utils.logger import get_logger

logger = get_logger("mcp.source_registry")

# ---------------------------------------------------------------------------
# MCP tool naming constraint (from Toolbox ``NameValidation``)
# ---------------------------------------------------------------------------
_VALID_NAME = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")


def _validate_name(name: str) -> None:
    """Enforce MCP name constraints.

    Stolen from Toolbox ``server/config.go:NameValidation`` — tool/source
    names must be 1-128 chars, alphanumeric + underscore/hyphen/dot only.
    """
    if not _VALID_NAME.match(name):
        raise ValueError(
            f"Invalid MCP resource name '{name}'. "
            "Must be 1-128 chars: [a-zA-Z0-9_.-]"
        )


# ---------------------------------------------------------------------------
# Source Protocol — mirrors Toolbox ``Source`` interface
# ---------------------------------------------------------------------------
@runtime_checkable
class MCPSource(Protocol):
    """Protocol for initialized MCP data sources.

    Mirrors Toolbox ``Source`` interface (``sources.go:63-66``):
    - ``source_type()`` → string identifier
    - ``name`` → unique name for cross-referencing from tools
    """

    @property
    def name(self) -> str: ...

    @property
    def source_type(self) -> str: ...

    def health_check(self) -> bool: ...


# ---------------------------------------------------------------------------
# Source Config — mirrors Toolbox ``SourceConfig`` interface
# ---------------------------------------------------------------------------
@runtime_checkable
class MCPSourceConfig(Protocol):
    """Configuration declaration for a source (the YAML representation).

    Mirrors Toolbox ``SourceConfig`` (``sources.go:57-60``):
    - ``source_config_type()`` → type string for registry dispatch
    - ``initialize()`` → creates the live ``MCPSource``
    """

    @property
    def source_config_type(self) -> str: ...

    def initialize(self) -> MCPSource: ...


# ---------------------------------------------------------------------------
# Concrete: SQL Source (postgres, mysql, sqlite via SQLAlchemy)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SQLSourceConfig:
    """Declarative config for a SQLAlchemy-compatible database source.

    Mirrors Toolbox ``postgres.Config`` (``sources/postgres/postgres.go:51-61``).
    Supports any SQLAlchemy dialect: postgres, mysql, sqlite, oracle, mssql.
    """

    name: str
    connection_string: str
    kind: str = "postgres"  # postgres | mysql | sqlite | oracle | mssql
    schema: Optional[str] = None
    read_only: bool = True

    @property
    def source_config_type(self) -> str:
        return self.kind

    def initialize(self) -> SQLSource:
        """Create a live SQLAlchemy engine and validate the connection.

        Mirrors Toolbox ``postgres.Config.Initialize()`` which creates
        a pgxpool and pings it before returning.
        """
        _validate_name(self.name)
        engine = create_engine(self.connection_string)

        # Discover schema metadata via reflection (our unique advantage)
        insp = inspect(engine)
        target_schema = self.schema or insp.default_schema_name
        available_tables = insp.get_table_names(schema=target_schema)

        logger.info(
            "source_initialized",
            name=self.name,
            kind=self.kind,
            schema=target_schema,
            tables_found=len(available_tables),
        )

        return SQLSource(
            _name=self.name,
            _kind=self.kind,
            engine=engine,
            schema=target_schema,
            tables=available_tables,
            read_only=self.read_only,
            _config=self,
        )


@dataclass
class SQLSource:
    """A live, initialized SQL data source.

    Mirrors Toolbox ``postgres.Source`` (``sources/postgres/postgres.go:87-90``).
    Unlike Toolbox, we also carry reflected table metadata because CentRAG
    generates tools dynamically — our unique advantage over static YAML tools.
    """

    _name: str
    _kind: str
    engine: Engine
    schema: str
    tables: list[str]
    read_only: bool
    _config: SQLSourceConfig

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_type(self) -> str:
        return self._kind

    def health_check(self) -> bool:
        """Verify the connection is alive."""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    __import__("sqlalchemy").text("SELECT 1")
                )
            return True
        except Exception:
            return False

    def to_config(self) -> SQLSourceConfig:
        """Round-trip back to config (mirrors Toolbox ``ToConfig()``)."""
        return self._config


# ---------------------------------------------------------------------------
# Source Registry — mirrors Toolbox ``sourceRegistry`` global map
# ---------------------------------------------------------------------------
class SourceRegistry:
    """Central registry mapping source names → live Source instances.

    Stolen from Toolbox ``sources.go:30-41``:
    ```go
    var sourceRegistry = make(map[string]SourceConfigFactory)
    func Register(sourceType string, factory SourceConfigFactory) bool { ... }
    ```

    The WHY:
        By decoupling sources from tools, one database connection can serve
        multiple tool families (data tools, monitoring tools, health tools)
        exactly like Toolbox's prebuilt postgres config does with toolsets.
    """

    # Type → Config factory (mirrors Toolbox's ``sourceRegistry``)
    _type_factories: ClassVar[Dict[str, type]] = {
        "postgres": SQLSourceConfig,
        "mysql": SQLSourceConfig,
        "sqlite": SQLSourceConfig,
        "oracle": SQLSourceConfig,
        "mssql": SQLSourceConfig,
    }

    def __init__(self) -> None:
        self._sources: Dict[str, MCPSource] = {}

    def register_type(self, source_type: str, factory: type) -> bool:
        """Register a new source type factory.

        Mirrors Toolbox ``sources.Register()`` — returns False if
        the type is already registered (no silent overwrites).
        """
        if source_type in self._type_factories:
            return False
        self._type_factories[source_type] = factory
        return True

    def add(self, config: MCPSourceConfig) -> MCPSource:
        """Initialize and register a source from its config declaration."""
        source = config.initialize()
        self._sources[source.name] = source
        logger.info("source_registered", name=source.name, type=source.source_type)
        return source

    def get(self, name: str) -> Optional[MCPSource]:
        """Look up a source by name (mirrors Toolbox ``SourceProvider.GetSource()``)."""
        return self._sources.get(name)

    def get_sql(self, name: str) -> Optional[SQLSource]:
        """Type-narrowed getter for SQL sources (mirrors Toolbox ``GetCompatibleSource[T]``)."""
        src = self._sources.get(name)
        if isinstance(src, SQLSource):
            return src
        return None

    def remove(self, name: str) -> bool:
        """Unregister a source by name."""
        if name in self._sources:
            del self._sources[name]
            return True
        return False

    def list_sources(self) -> Dict[str, str]:
        """List all registered sources with their types."""
        return {name: src.source_type for name, src in self._sources.items()}

    @property
    def count(self) -> int:
        return len(self._sources)
