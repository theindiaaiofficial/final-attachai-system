from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv", ".json"}


@dataclass(frozen=True)
class ParsedSection:
    text: str
    page: int | None = None
    title: str | None = None


def parse_file(path: Path) -> list[ParsedSection]:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext or '(none)'}")
    if ext in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8-sig").replace("\x00", "").strip()
        return [ParsedSection(text, title=path.stem)] if text else []
    if ext == ".pdf":
        from pypdf import PdfReader
        sections = []
        for page_no, page in enumerate(PdfReader(str(path)).pages, 1):
            text = (page.extract_text() or "").replace("\x00", "").strip()
            if text:
                sections.append(ParsedSection(text, page=page_no, title=path.stem))
        return sections
    if ext == ".docx":
        from docx import Document
        doc = Document(str(path)); lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            lines.extend(" | ".join(cell.text.strip().replace("\n", " / ") for cell in row.cells) for row in table.rows)
        text = "\n".join(line for line in lines if line)
        return [ParsedSection(text, title=path.stem)] if text else []
    if ext == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            return []
        sections = []
        for row_no, row in enumerate(rows[1:], 2):
            pairs = [f"{rows[0][i] if i < len(rows[0]) and rows[0][i] else f'column_{i+1}'}: {v.strip()}" for i, v in enumerate(row) if v.strip()]
            if pairs:
                sections.append(ParsedSection("\n".join(pairs), title=f"{path.stem} — row {row_no}"))
        return sections
    payload: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    text = json.dumps(payload, ensure_ascii=False, indent=2).strip()
    return [ParsedSection(text, title=path.stem)] if text else []
