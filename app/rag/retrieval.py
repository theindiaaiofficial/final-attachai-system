from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.providers.embeddings import EmbeddingProvider
from app.repositories.sqlite import SQLiteRepository


@dataclass
class RetrievalResult:
    chunks: list[dict[str, Any]]
    context: str


class Retriever:
    def __init__(self, settings: Settings, embeddings: EmbeddingProvider, repository: SQLiteRepository):
        self.settings, self.embeddings, self.repository = settings, embeddings, repository

    async def retrieve(self, tenant_id: str, query: str) -> RetrievalResult:
        vector = await self.embeddings.embed_query(query)
        hits = self.repository.search_chunks(tenant_id, vector, self.settings.rag_top_k, self.settings.rag_min_similarity)
        selected: list[dict[str, Any]] = []; seen: set[str] = set(); blocks: list[str] = []; used = 0
        for hit in hits:
            normalized = " ".join(hit["text"].casefold().split())
            if normalized in seen:
                continue
            meta = hit["metadata"]; source_id = f"S{len(selected) + 1}"
            page = f", page {meta['page_number']}" if isinstance(meta.get("page_number"), int) and meta["page_number"] > 0 else ""
            block = f"[{source_id}] source={meta.get('source_filename', 'unknown')}{page}; title={meta.get('document_title') or ''}; similarity={hit['similarity']:.3f}\n{hit['text']}"
            if used + len(block) > self.settings.rag_max_context_chars:
                break
            hit["source_id"] = source_id; selected.append(hit); blocks.append(block); seen.add(normalized); used += len(block)
        return RetrievalResult(selected, "\n\n---\n\n".join(blocks))
