# 0001. Use Composition Root for Dependency Injection

Date: 2026-04-10

## Status
Accepted

## Context
When building a multi-tenant retrieval-augmented generation engine, we need maximum modularity to toggle between `NoOpEmbedder` (for tests) and highly parallel production embedders (`OpenAIEmbedder`, `BedrockEmbedder`). If dependencies are instantiated across various `__init__` methods deep linking the core architecture, the system becomes rigid and untestable (violating SOLID Dependency Inversion).

## Decision
We decided to strict-enforce a **Composition Root** pattern within `centrag/wiring.py`. All concrete implementations will be assembled here at application startup and passed explicitly via interfaces/Protocols. Component logic (`centrag/retrieval/engine.py` etc.) will never instantiate dependencies directly and will solely depend on `abstractions/`.

## Consequences
- **Positive:** Agents executing the `microservices-patterns` or `architecture-patterns` skills can easily mock interfaces without disrupting core RAG logic. Testing overhead drops to zero-latency because `noop_*.py` tools can be predictably wired.
- **Negative:** It increases the upfront bootstrap complexity. `wiring.py` acts as a bottleneck that must be rigorously maintained when adding new SDK integrations.
