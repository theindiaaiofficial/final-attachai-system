from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_expired_conversations_are_deleted_with_their_messages(repository):
    client = repository.create_client(
        "Retention Test",
        "retention-test",
        ["https://retention.example"],
        {},
        "Test prompt",
    )
    expired = repository.create_conversation(client["id"])
    repository.save_message(client["id"], expired, "user", "old message")

    with repository._db() as db:
        old_created_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        db.execute(
            "UPDATE conversations SET created_at=? WHERE id=?",
            (old_created_at, expired),
        )

    active = repository.create_conversation(client["id"])
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()

    assert repository.delete_expired_conversations(cutoff) == 1
    assert repository.get_conversation(client["id"], expired) is None
    assert repository.get_conversation(client["id"], active) is not None
