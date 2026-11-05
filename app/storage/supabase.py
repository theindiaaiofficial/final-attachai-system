from __future__ import annotations

from urllib.parse import quote

import httpx


class SupabaseStorage:
    name = "supabase"

    def __init__(self, url: str, service_role_key: str, bucket: str):
        self.base_url = url.rstrip("/") + "/storage/v1/object"
        self.bucket = bucket
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def put(self, tenant_id: str, source_id: str, filename: str, data: bytes) -> str:
        path = quote(f"{tenant_id}/{source_id}/{filename}", safe="/")
        with httpx.Client(timeout=30) as client:
            response = client.post(f"{self.base_url}/{self.bucket}/{path}", headers={**self.headers, "x-upsert": "true", "Content-Type": "application/octet-stream"}, content=data)
        response.raise_for_status()
        return path

    def delete(self, tenant_id: str, source_id: str, filename: str) -> None:
        path = f"{tenant_id}/{source_id}/{filename}"
        with httpx.Client(timeout=20) as client:
            response = client.request("DELETE", f"{self.base_url}/{self.bucket}", headers=self.headers, json={"prefixes": [path]})
        response.raise_for_status()

    def get(self, tenant_id: str, source_id: str, filename: str) -> bytes:
        path = quote(f"{tenant_id}/{source_id}/{filename}", safe="/")
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{self.base_url}/{self.bucket}/{path}", headers=self.headers)
        response.raise_for_status()
        if len(response.content) > 10 * 1024 * 1024:
            raise ValueError("Stored source exceeds size limit")
        return response.content

    def health(self) -> dict[str, str]:
        return {"provider": self.name, "status": "configured"}
