from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTING = "CONFLICTING"


class EvidenceEvaluation(BaseModel):
    status: EvidenceStatus
    supported_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    reason: str = Field("", max_length=800)
    available: bool = True


_STOP_WORDS = {
    # English question glue / generic words
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "can", "could", "would", "should", "will", "may",
    "i", "we", "you", "your", "my", "our", "their", "they", "it", "its",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "and", "or", "but", "if", "then", "than", "to", "of", "for", "from",
    "in", "on", "at", "by", "with", "about", "as", "into", "after", "before",
    "please", "tell", "me", "show", "give", "explain", "let", "know",
    # Hindi / Hinglish function words
    "aap", "ap", "kya", "ka", "ki", "ke", "ko", "hai", "hain", "ho",
    "kaise", "kab", "kahan", "kyun", "aur", "mera", "meri", "mere",
    "mujhe", "hum", "ham", "aapka", "aapki", "karo", "karna", "batao",
}

_SYNONYMS: dict[str, set[str]] = {
    "cost": {"cost", "price", "pricing", "fee", "fees", "charge", "charges", "amount"},
    "pay": {"pay", "payment", "paid", "fee", "fees", "charge", "charges", "wise"},
    "services": {"service", "services", "offer", "offers", "provide", "provides", "includes", "include"},
    "provide": {"provide", "provides", "offered", "offer", "offers", "service", "services", "include", "includes"},
    "setup": {"setup", "set-up", "configure", "configuration", "configured", "initial"},
    "install": {"install", "installation", "snippet", "embed", "add", "deploy", "redeploy"},
    "support": {"support", "supported", "compatibility", "compatible", "integration", "integrations"},
    "founder": {"founder", "creator", "created", "owner"},
    "refund": {"refund", "refunded", "reimbursement"},
    "guarantee": {"guarantee", "guaranteed", "promise", "promised"},
    "visitor": {"visitor", "visitors", "website", "site", "chat"},
    "delete": {"delete", "remove", "clear", "erase"},
    "remain": {"remain", "available", "retain", "retained", "expires", "expire", "expiry"},
    "information": {"information", "details", "knowledge", "data", "content"},
    "business": {"business", "company", "client", "customer"},
}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+|[\u0900-\u097f]+", text.casefold())
        if len(token) > 1 and token not in _STOP_WORDS
    }


def _variants(token: str) -> set[str]:
    return _SYNONYMS.get(token, {token})


def _coverage(question: str, evidence_text: str) -> tuple[float, list[str], list[str]]:
    question_terms = _tokens(question)
    evidence_terms = _tokens(evidence_text)
    if not question_terms:
        return 0.0, [], []

    matched: list[str] = []
    missing: list[str] = []
    for term in sorted(question_terms):
        if _variants(term).intersection(evidence_terms):
            matched.append(term)
        else:
            missing.append(term)

    return len(matched) / len(question_terms), matched, missing


def answer_is_lexically_supported(
    answer: str,
    chunks: list[dict[str, Any]],
    valid_source_ids: set[str],
) -> bool:
    """Conservative outage-only guard; the normal path still uses the LLM verifier."""
    cited_ids = set(re.findall(r"\[(S\d+)\]", answer))
    if not cited_ids or not cited_ids.issubset(valid_source_ids):
        return False

    evidence_text = " ".join(str(item.get("text", "")) for item in chunks)
    answer_without_citations = re.sub(r"\[S\d+\]", " ", answer)
    answer_terms = _tokens(answer_without_citations)
    evidence_terms = _tokens(evidence_text)
    if not answer_terms:
        return False

    # Numeric/price claims must match the retrieved source text exactly.
    answer_numbers = set(re.findall(r"(?<![a-z])\d+(?:[.,]\d+)?", answer_without_citations.casefold()))
    evidence_numbers = set(re.findall(r"(?<![a-z])\d+(?:[.,]\d+)?", evidence_text.casefold()))
    if not answer_numbers.issubset(evidence_numbers):
        return False

    supported = sum(
        1 for term in answer_terms if _variants(term).intersection(evidence_terms)
    )
    return supported / len(answer_terms) >= 0.58


class EvidenceEvaluator:
    """Local evidence-coverage heuristic; no provider request is made here.

    This is a conservative pre-check only. The separate grounding verifier
    remains responsible for checking the generated answer against tenant
    evidence before it is returned.
    """

    def __init__(self, _llm: Any | None = None):
        # Accept the former constructor argument for backwards compatibility.
        # It is intentionally unused: evidence coverage must not consume LLM TPM.
        self.llm = None

    async def evaluate(
        self,
        question: str,
        context: str,
        chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
        trace: Any | None = None,
    ) -> EvidenceEvaluation:
        if not chunks:
            result = EvidenceEvaluation(
                status=EvidenceStatus.INSUFFICIENT,
                missing_aspects=[question],
                reason="No tenant-scoped chunks were retrieved.",
            )
        else:
            evidence_text = " ".join(
                str(chunk.get("text", "")) for chunk in chunks
            )
            coverage, matched, missing = _coverage(question, evidence_text)

            # High lexical coverage is sufficient for the pre-check; moderate
            # coverage is partial. The later grounding verifier is still required.
            if coverage >= 0.70:
                status = EvidenceStatus.SUFFICIENT
            elif coverage >= 0.30:
                status = EvidenceStatus.PARTIAL
            else:
                status = EvidenceStatus.INSUFFICIENT

            result = EvidenceEvaluation(
                status=status,
                supported_aspects=matched,
                missing_aspects=missing,
                reason=(
                    f"Deterministic evidence-term coverage: {coverage:.0%}; "
                    "final factual validation is handled by grounding."
                ),
                available=True,
            )

        if trace:
            trace.emit(
                "evidence",
                "evaluation_deterministic",
                status="ok",
                metadata={
                    "status": result.status.value,
                    "available": result.available,
                    "matched_aspects": result.supported_aspects,
                    "missing_aspects": result.missing_aspects,
                    "provider_call": False,
                },
            )
        return result
