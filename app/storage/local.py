from __future__ import annotations

import re
from pathlib import Path


class LocalTenantStorage:
    name = "local-development"

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, source_id: str, filename: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[:180]
        path = self.root / tenant_id / source_id / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, tenant_id: str, source_id: str, filename: str, data: bytes) -> str:
        path = self._path(tenant_id, source_id, filename)
        path.write_bytes(data)
        return str(path)

    def delete(self, tenant_id: str, source_id: str, filename: str) -> None:
        path = self._path(tenant_id, source_id, filename)
        if path.exists():
            path.unlink()

    def get(self, tenant_id: str, source_id: str, filename: str) -> bytes:
        return self._path(tenant_id, source_id, filename).read_bytes()

    def health(self) -> dict[str, str]:
        return {"provider": self.name, "status": "ok"}
