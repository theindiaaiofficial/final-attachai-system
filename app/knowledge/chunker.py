from __future__ import annotations

from dataclasses import dataclass

from .parsers import ParsedSection


@dataclass(frozen=True)
class TextChunk:
    text: str
    index: int
    page: int | None
    title: str | None


def chunk_sections(sections: list[ParsedSection], size: int, overlap: int) -> list[TextChunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk size/overlap")
    result: list[TextChunk] = []
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        cursor = 0
        while cursor < len(text):
            end = min(len(text), cursor + size)
            if end < len(text):
                boundary = max(text.rfind("\n", cursor, end), text.rfind(". ", cursor, end), text.rfind(" ", cursor, end))
                if boundary > cursor + int(size * .65):
                    end = boundary + (2 if text[boundary:boundary + 2] == ". " else 1)
            piece = text[cursor:end].strip()
            if piece:
                result.append(TextChunk(piece, len(result), section.page, section.title))
            if end >= len(text):
                break
            cursor = max(cursor + 1, end - overlap)
    return result
