from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from app.config import Settings
from app.knowledge.chunker import chunk_sections
from app.knowledge.parsers import parse_file
from app.providers.embeddings import EmbeddingProvider
from app.repositories.sqlite import SQLiteRepository


class KnowledgeService:
    def __init__(self, settings: Settings, repository: SQLiteRepository, embeddings: EmbeddingProvider, storage: Any):
        self.settings, self.repository, self.embeddings, self.storage = settings, repository, embeddings, storage

    async def ingest(self, tenant_id: str, filename: str, content: bytes) -> dict[str, Any]:
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("File exceeds the 10 MB upload limit")
        safe_name = Path(filename).name
        if Path(safe_name).suffix.lower() not in {".txt", ".md", ".pdf", ".docx", ".csv", ".json"}:
            raise ValueError("Supported file types are TXT, Markdown, PDF, DOCX, CSV, and JSON")
        content_hash = hashlib.sha256(content).hexdigest()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / safe_name
                path.write_bytes(content)
                sections = parse_file(path)
                chunks = chunk_sections(sections, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap)
                if not chunks:
                    raise ValueError("No extractable text found; scanned/image-only PDFs require OCR outside this application")
                if len(chunks) > 10000:
                    raise ValueError("File produces too many chunks")
                vectors: list[list[float]] = []
                for start in range(0, len(chunks), self.settings.embedding_batch_size):
                    vectors.extend(await self.embeddings.embed_documents([chunk.text for chunk in chunks[start:start + self.settings.embedding_batch_size]]))
                if len(vectors) != len(chunks):
                    raise ValueError("Embedding count did not match chunk count")
                # Preserve the serving source until parse and embedding work succeeds.
                source_id = await asyncio.to_thread(self.repository.save_file, tenant_id, safe_name, content_hash, len(content))
                await asyncio.to_thread(self.storage.put, tenant_id, source_id, safe_name, content)
                self.repository.save_chunks(tenant_id, source_id, safe_name, [{"index": chunk.index, "text": chunk.text, "page": chunk.page, "title": chunk.title, "embedding": vector} for chunk, vector in zip(chunks, vectors, strict=True)])
                self.repository.finish_file(tenant_id, source_id, "ready")
                return {"id": source_id, "filename": safe_name, "status": "ready", "chunks": len(chunks), "content_hash": content_hash}
        except Exception as exc:
            if "source_id" in locals():
                self.repository.finish_file(tenant_id, source_id, "error", type(exc).__name__)
            raise

    async def rebuild(self, tenant_id: str) -> dict[str, Any]:
        results = []
        for item in await asyncio.to_thread(self.repository.list_files, tenant_id):
            try:
                content = await asyncio.to_thread(self.storage.get, tenant_id, item["id"], item["filename"])
                results.append(await self.ingest(tenant_id, item["filename"], content))
            except Exception as exc:
                results.append({"filename": item["filename"], "status": "error", "error": type(exc).__name__})
        return {"status": "completed_with_errors" if any(x["status"] == "error" for x in results) else "completed", "items": results}

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.repository.list_files(tenant_id)

    def delete(self, tenant_id: str, filename: str) -> bool:
        safe_name = Path(filename).name
        existing = next((item for item in self.repository.list_files(tenant_id) if item["filename"] == safe_name), None)
        if not existing:
            return False
        # Remove the durable object first; if that fails the manifest remains
        # visible and reconciliation can retry without losing its locator.
        self.storage.delete(tenant_id, existing["id"], safe_name)
        return self.repository.delete_file(tenant_id, safe_name)
