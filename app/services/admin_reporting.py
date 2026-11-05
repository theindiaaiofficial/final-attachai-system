"""Honest reporting from persisted rows, shared by both persistence adapters."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any


def aggregate(records: dict[str, list[dict[str, Any]]], days: int = 30) -> dict[str, Any]:
    start = datetime.now(UTC).date() - timedelta(days=days - 1)
    buckets = {str(start + timedelta(days=i)): {"date": str(start + timedelta(days=i)), "conversations": 0, "leads": 0, "requests": 0} for i in range(days)}
    for family, field in (("conversations", "conversations"), ("leads", "leads"), ("usage_logs", "requests")):
        for item in records[family]:
            day = str(item["created_at"])[:10]
            if day in buckets:
                buckets[day][field] += 1
    usage = records["usage_logs"]
    latencies = [float(item["latency_ms"]) for item in usage]
    return {
        "conversations": len(records["conversations"]), "leads": len(records["leads"]),
        "messages": sum(int(item.get("message_count", 0)) for item in records["conversations"]),
        "requests": len(usage), "average_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "documents": len(records["knowledge_files"]),
        "knowledge_status": dict(Counter(item["status"] for item in records["knowledge_files"])),
        "routes": dict(Counter(item["kind"] for item in usage)), "series": list(buckets.values()),
        "period_days": days,
    }


def client_usage(records: dict[str, list[dict[str, Any]]], clients: list[dict]) -> list[dict]:
    counts = defaultdict(lambda: {"conversations": 0, "leads": 0, "requests": 0})
    for family, field in (("conversations", "conversations"), ("leads", "leads"), ("usage_logs", "requests")):
        for row in records[family]:
            counts[row["client_id"]][field] += 1
    return [{"id": item["id"], "name": item["name"], **counts[item["id"]]} for item in clients]
