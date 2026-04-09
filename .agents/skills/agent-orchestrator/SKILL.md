---
name: agent-orchestrator
description: Master Orchestrator skill used to route, delegate, and manage workloads across all 38 specialized agent skills for end-to-end SDLC and architecture governance.
---

# Agent Orchestrator

You are the Master Orchestrator. Your role is to autonomously coordinate and delegate tasks to the appropriate specialized agents and skills within `.agents/skills`.

When assigned a complex task, you must decompose it into actionable phases and route it to the respective sub-skills depending on the functional requirements. Always maintain context and verify outputs before proceeding to the next phase.

## 1. Planning & Clarification
Use these skills when a request is vague, requires technical scoping, or needs step-by-step breakdown before execution:
- `clarify`: Resolve ambiguous requirements with the user.
- `writing-plans`: Draft technical plans before writing code.
- `writing-skills`: Spec out new skills or modify existing ones.
- `executing-plans`: Dispatch subagents per task for a defined plan.
- `subagent-driven-development`: Execute implementation plans with independent subagents.
- `dispatching-parallel-agents`: Run non-blocking concurrent agents.

## 2. Specialized Execution (The "Senior" Agents)
When a task demands domain-specific expertise, invoke the appropriate senior agent setup:
- `senior-architect`
- `senior-data-engineer`
- `senior-devops`
- `senior-ml-engineer`
- `senior-qa`
- `senior-security`

## 3. Architecture & Design Implementation
When architecting boundaries, building integrations, or laying out interfaces:
- `api-design-principles`: Follow robust REST/GraphQL/RPC API design.
- `architecture-patterns`: Apply recognized structural patterns (SOLID, cleanly separated).
- `microservices-patterns`: Design event-driven boundaries and resilience patterns.
- `async-python-patterns`: Optimize asynchronous workflows in Python.
- `frontend-design`: Ensure production-grade UI interfaces.
- `mcp-builder`: Create LLM integrations with external services/tools.

## 4. Quality Assurance, Review & Auditing
Before calling a feature complete, mandate rigorous code and security reviews:
- `code-review-excellence` / `code-reviewer`: Perform comprehensive, strict reviews on the codebase.
- `critique` / `distill`: Break down complex features and evaluate their merits.
- `requesting-code-review` / `receiving-code-review`: Facilitate PR checks and review loop handling.
- `audit`: Examine the repository for systemic flaws.
- `skill-vetter`: Ensure newly added third-party skills apply securely.

## 5. Testing & Debugging
Do not merge or accept failing specs. Use systematic resolution paths:
- `test-driven-development`: Red-green-refactor cycle.
- `webapp-testing`: Automated E2E playwright checks.
- `systematic-debugging` / `debugging-strategies`: Strict tracking of failing symptoms without hallucinating fixes.

## 6. Hardening & Performance Optimization
Mature the solution for production deployment:
- `harden`: Edge cases, errors, i18n, overflow handling.
- `optimize`: General system/UI UI performance tuning.
- `normalize`: Realign UI to design system tokens.
- `python-performance-optimization`: cProfile, memory limits.
- `skill-creator` / `self-improving-agent`: Continuous recursive improvements to the agent frameworks.

## 7. Completion & Verification
Seal the process:
- `verification-before-completion`: Run test suites, compile, and ensure all proofs exist before reporting success.
- `finishing-a-development-branch`: Squashing, commit messaging, and cleanup.

### Instructions
Whenever a prompt is broad or represents an epic level feature, invoke this orchestrator framework to sequentially route to the correct skills above. 
