from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings


class EmbeddingProvider(Protocol):
    dimension: int
    fingerprint: str
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class GeminiEmbeddings:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dimension = settings.embedding_output_dimensionality
        self.fingerprint = f"gemini:{settings.embedding_model}:{self.dimension}"

    def _client(self):
        key = self.settings.embedding_api_key or self.settings.gemini_api_key
        if not key:
            raise RuntimeError("Embedding provider credentials are not configured")
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("google-genai is not installed") from exc
        return genai.Client(api_key=key.get_secret_value())

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text], task_type="RETRIEVAL_QUERY"))[0]

    async def embed_documents(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        if not texts:
            return []
        client = self._client()
        response = await __import__("asyncio").to_thread(
            client.models.embed_content,
            model=self.settings.embedding_model,
            contents=texts,
            config={"task_type": task_type, "output_dimensionality": self.dimension},
        )
        values = [list(item.values) for item in response.embeddings]
        if any(len(value) != self.dimension for value in values):
            raise RuntimeError("Embedding provider returned an unexpected vector dimension")
        return values


class OpenAICompatibleEmbeddings:
    """Generic `/embeddings` transport for a future non-Gemini provider."""

    def __init__(self, settings: Settings):
        key = settings.embedding_api_key or settings.gemini_api_key
        if not key or not settings.embedding_api_base:
            raise RuntimeError("EMBEDDING_API_KEY and EMBEDDING_API_BASE are required")
        self.settings = settings
        self.key = key.get_secret_value()
        self.dimension = settings.embedding_output_dimensionality
        self.fingerprint = f"{settings.embedding_provider}:{settings.embedding_model}:{self.dimension}"

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.settings.embedding_api_base.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.settings.embedding_model, "input": texts},
            )
        response.raise_for_status()
        values = [item["embedding"] for item in sorted(response.json()["data"], key=lambda item: item["index"])]
        if any(len(value) != self.dimension for value in values):
            raise RuntimeError("Embedding provider returned an unexpected vector dimension")
        return values
