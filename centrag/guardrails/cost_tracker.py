"""
InMemoryCostTracker — fulfills the CostTrackerProtocol.

Previously declared in guardrails.py but never implemented.
This provides a working in-memory implementation for development/testing.

Uses the BUDGET_LIMITS dict that was previously declared but never referenced.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from centrag.utils.logger import get_logger

logger = get_logger("guardrails.cost")


# Budget limits per tier (tokens per day)
# Previously declared in guardrails.py L268-272 but never used.
BUDGET_LIMITS: dict[str, int] = {
    "free": 50_000,          # ~$0.15/day
    "standard": 200_000,     # ~$0.60/day
    "pro": 500_000,          # ~$1.50/day
    "premium": 2_000_000,    # ~$6.00/day
    "enterprise": 5_000_000, # ~$15/day
}


@dataclass
class TokenUsage:
    """Tracks token usage for a single request."""
    embedding_tokens: int = 0
    generation_input_tokens: int = 0
    generation_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.embedding_tokens
            + self.generation_input_tokens
            + self.generation_output_tokens
        )

    @property
    def estimated_cost_usd(self) -> float:
        """
        Estimated cost using Bedrock pricing (approximate):
        - Titan Embed v2:       $0.0001 / 1K tokens
        - Claude 3.5 Sonnet in: $0.003  / 1K tokens
        - Claude 3.5 Sonnet out:$0.015  / 1K tokens
        """
        embed_cost = (self.embedding_tokens / 1000) * 0.0001
        input_cost = (self.generation_input_tokens / 1000) * 0.003
        output_cost = (self.generation_output_tokens / 1000) * 0.015
        return embed_cost + input_cost + output_cost


class InMemoryCostTracker:
    """
    In-memory cost tracker for development and testing.

    Implements the CostTrackerProtocol that was declared in the original
    guardrails.py but never had a concrete implementation.

    Tracks per-team, per-day token usage in a dict.
    NOT suitable for production (no persistence, no cross-instance sharing).
    For production, use a Redis-backed implementation.
    """

    def __init__(self) -> None:
        # {team_id: {date_str: TokenUsage}}
        self._usage: dict[str, dict[str, TokenUsage]] = defaultdict(dict)

    async def get_usage(self, team_id: str, period: str = "daily") -> TokenUsage:
        """Get current period usage for a team."""
        today = date.today().isoformat()
        team_usage = self._usage.get(team_id, {})
        return team_usage.get(today, TokenUsage())

    async def record_usage(self, team_id: str, usage: TokenUsage) -> None:
        """Record usage for a request."""
        today = date.today().isoformat()
        if today not in self._usage[team_id]:
            self._usage[team_id][today] = TokenUsage()

        current = self._usage[team_id][today]
        current.embedding_tokens += usage.embedding_tokens
        current.generation_input_tokens += usage.generation_input_tokens
        current.generation_output_tokens += usage.generation_output_tokens

        logger.debug(
            "usage_recorded",
            team_id=team_id,
            request_tokens=usage.total_tokens,
            daily_total=current.total_tokens,
        )

    async def check_budget(self, team_id: str, tier: str = "pro") -> bool:
        """Returns True if team is within budget, False if over."""
        current = await self.get_usage(team_id)
        limit = BUDGET_LIMITS.get(tier, BUDGET_LIMITS["pro"])

        within_budget = current.total_tokens < limit
        if not within_budget:
            logger.warning(
                "budget_exceeded",
                team_id=team_id,
                tier=tier,
                usage=current.total_tokens,
                limit=limit,
            )
        return within_budget

    def reset(self, team_id: str | None = None) -> None:
        """Reset usage counters (for testing)."""
        if team_id:
            self._usage.pop(team_id, None)
        else:
            self._usage.clear()
