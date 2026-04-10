# ADR-007: Mandatory 3-AZ AWS Deployment Architecture

## Status
Accepted

## Context
High availability (HA) limits for foundational enterprise architecture strongly index on the blast radius scaling limits during datacenter failover events.
A single Availability Zone (AZ) failure should drop maximum compute limits by exactly 33%, allowing elastic overflow without completely breaking service level agreements (SLAs).

## Decision
All core stateful infrastructures (Aurora PostgreSQL, ElastiCache Redis) and stateless computing matrices (ECS Fargate workloads) must be actively provisioned across **3 distinct Availability Zones (AZs)** synchronously within the target `us-east-1` deployment region.

## Consequences
1. **Pros:**
   - Satisfies 99.9% uptime SLA constraints.
   - Blast radiuses for catastrophic physical datacenter power failures are structurally limited.
2. **Cons:**
   - Drastically increases absolute base cost for non-trafficked Dev servers.
   - Increases Cross-AZ networking chatter pricing.
