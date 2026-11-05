"""Secret-safe JSONL request tracing with bounded local rotation."""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|bearer|password|token)\s*[:=]\s*[^\s,;]+")


class TraceRecorder:
    def __init__(self, settings: Any, trace_id: str, client_id: str | None = None, session_id: str | None = None):
        self.settings = settings
        self.trace_id = trace_id
        self.client_id = client_id
        self.session_id = session_id
        self.started = time.perf_counter()
        self.enabled = bool(getattr(settings, "orbit_trace_debug", False))
        self.include_content = bool(
            self.enabled
            and getattr(settings, "orbit_trace_include_content", False)
            and getattr(settings, "app_env", "development").casefold() not in {"production", "prod"}
        )

    def _safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._safe(item) for key, item in value.items() if str(key).casefold() not in {"api_key", "authorization", "password", "secret", "token"}}
        if isinstance(value, (list, tuple)):
            return [self._safe(item) for item in value]
        if isinstance(value, str):
            return _SECRET.sub(r"\1=[REDACTED]", value)[:2000]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:500]

    def emit(self, stage: str, event: str, *, status: str = "ok", metadata: dict[str, Any] | None = None, content: str | None = None, error: str | None = None) -> None:
        if not self.enabled:
            return
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "trace_id": self.trace_id,
            "client_id": self.client_id,
            "session_id": self.session_id,
            "stage": stage,
            "event": event,
            "status": status,
            "duration_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "metadata": self._safe(metadata or {}),
        }
        if self.include_content and content is not None:
            record["content"] = self._safe(content)
        if error:
            record["error_type"] = type(error).__name__ if isinstance(error, Exception) else str(error)[:120]
            if getattr(self.settings, "app_env", "development").casefold() not in {"production", "prod"}:
                record["stack"] = self._safe(traceback.format_exc())[:4000]
        path = Path(getattr(self.settings, "orbit_trace_log_path", "data/logs/orbit-trace.jsonl"))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _LOCK:
                if path.exists() and path.stat().st_size >= int(getattr(self.settings, "orbit_trace_max_bytes", 5_000_000)):
                    rotated = path.with_suffix(path.suffix + ".1")
                    if rotated.exists():
                        rotated.unlink()
                    path.replace(rotated)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            # Diagnostics must never break a customer conversation.
            return
