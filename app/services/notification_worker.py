from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutboxPolicy:
    """Delivery is deliberately separate from enqueueing and remains pending without a transport."""

    max_attempts: int = 5
    lease_seconds: int = 300


class NotificationWorker:
    """Boundary for a future email/webhook worker.

    Lead creation only persists `pending` outbox rows. A configured transport
    can claim rows with a database lease and transition them to sent/failed;
    no adapter is silently treated as delivery success.
    """

    def __init__(self, policy: OutboxPolicy | None = None):
        self.policy = policy or OutboxPolicy()
