from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.domain.schemas import Citation, RouteName
from app.observability.tracing import TraceRecorder
from app.rag.evidence import (
    answer_is_lexically_supported,
    EvidenceEvaluator,
    EvidenceStatus,
)
from app.rag.generation import AnswerGenerator
from app.rag.grounding import GroundingStatus, GroundingVerifier
from app.rag.identity import (
    identity_response,
    identity_system_context,
    is_identity_question,
    resolve_identity,
)
from app.rag.retrieval import Retriever
from app.rag.router import deterministic_smalltalk_response, IntelligenceRouter
from app.repositories.sqlite import SQLiteRepository


class ChatPipeline:
    """The sole public conversation orchestrator, following the RAG-2.0 sequence."""

    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        router: IntelligenceRouter,
        retriever: Retriever,
        evaluator: EvidenceEvaluator,
        generator: AnswerGenerator,
        verifier: GroundingVerifier,
    ):
        (
            self.settings,
            self.repository,
            self.router,
            self.retriever,
            self.evaluator,
            self.generator,
            self.verifier,
        ) = (settings, repository, router, retriever, evaluator, generator, verifier)

    @staticmethod
    def _citations(chunks: list[dict[str, Any]], allowed: set[str]) -> list[Citation]:
        result = []
        for chunk in chunks:
            if chunk.get("source_id") not in allowed:
                continue
            metadata = chunk.get("metadata", {})
            result.append(
                Citation(
                    source_id=chunk["source_id"],
                    filename=str(metadata.get("source_filename", "unknown")),
                    page=metadata.get("page_number"),
                    title=metadata.get("document_title"),
                    excerpt=" ".join(chunk["text"].split())[:360],
                )
            )
        return result

    @staticmethod
    def _apply_verified_citations(
        answer: str,
        chunks: list[dict[str, Any]],
        allowed_source_ids: set[str],
    ) -> tuple[str, list[Citation]]:
        """Use verifier-approved sources, not model-generated citation labels.

        The answer model can cite a retrieved source that the grounding
        verifier did not approve. In that case, intersecting the two sets
        incorrectly discards an otherwise verified answer. The verifier's
        source IDs are authoritative; model-generated labels are replaced.
        """
        citations = ChatPipeline._citations(chunks, allowed_source_ids)
        if not citations:
            return answer, []

        # Remove single or grouped labels emitted by the answer model, then
        # add only the source IDs approved by grounding verification.
        cleaned_answer = re.sub(
            r"\s*\[(?:S\d+)(?:\s*,\s*S\d+)*\]",
            "",
            answer,
        ).rstrip()
        verified_labels = " ".join(f"[{citation.source_id}]" for citation in citations)
        return f"{cleaned_answer}\n\nSources: {verified_labels}", citations

    @staticmethod
    def _fallback(
        chunks: list[dict[str, Any]],
        conflict: bool = False,
    ) -> tuple[str, list[Citation]]:

        if not chunks:
            return (
                "I don't have relevant business information indexed for that yet.",
                [],
            )

        source_ids = {item["source_id"] for item in chunks[:2]}

        citations = ChatPipeline._citations(
            chunks[:2],
            source_ids,
        )

        if conflict:
            answer = (
                "I found conflicting information in the available "
                "business documents. I cannot confidently confirm "
                "which detail is correct. Please contact the business "
                "for confirmation."
            )
        else:
            answer = (
                "I found related information in the business documents, "
                "but I could not verify a complete answer. Please try "
                "rephrasing your question or contact the business "
                "for confirmation."
            )

        return answer, citations

    def _provider_meta(self) -> dict[str, Any]:
        try:
            cfg = self.settings.provider_configuration("answer")
            return {"provider": cfg["provider"], "model": cfg["model"]}
        except Exception:
            return {}

    async def handle(
        self,
        tenant_id: str,
        message: str,
        session_id: str | None,
        request_id: str,
        on_progress: Callable[[str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        trace = TraceRecorder(self.settings, request_id, tenant_id, session_id)
        trace.emit(
            "request",
            "request_received",
            metadata={
                "endpoint": "/v1/chat",
                "input_length": len(message.strip()),
                "session_supplied": bool(session_id),
            },
            content=message,
        )
        try:
            result = await self._handle(
                tenant_id, message, session_id, request_id, trace, on_progress, on_token
            )
            trace.session_id = result["session_id"]
            trace.emit(
                "final_response",
                "response_completed",
                metadata={
                    "route": result["route"],
                    "answer_length": len(result["answer"]),
                    "citation_ids": [item.source_id for item in result["citations"]],
                    "evidence_status": result.get("evidence_status"),
                    "total_ms": round((time.perf_counter() - trace.started) * 1000, 2),
                },
            )
            return result
        except Exception as exc:
            trace.emit(
                "error",
                "pipeline_failed",
                status="error",
                error=exc,
                metadata={"exception_type": type(exc).__name__},
            )
            raise

    async def _handle(
        self,
        tenant_id: str,
        message: str,
        session_id: str | None,
        request_id: str,
        trace: TraceRecorder,
        on_progress: Callable[[str], None] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if on_progress:
            on_progress("preparing")
        if not message.strip():
            raise ValueError("Message cannot be empty")
        client = self.repository.get_client(tenant_id)
        if not client:
            raise KeyError("Tenant not found")

        identity = resolve_identity(client)
        identity_context = identity_system_context(identity)
        trace.emit(
            "identity",
            "identity_loaded",
            metadata={
                "assistant_name": identity.assistant_name,
                "business_name": identity.business_name,
                "description_configured": bool(identity.description),
                "identity_instructions_configured": bool(identity.instructions),
            },
        )

        session_id = session_id or self.repository.create_conversation(tenant_id)
        trace.session_id = session_id
        if not self.repository.conversation_exists(tenant_id, session_id):
            raise KeyError("Conversation not found")
        trace.emit(
            "history",
            "history_lookup_started",
            metadata={"limit": self.settings.max_history_messages},
        )
        history = self.repository.history(
            tenant_id, session_id, self.settings.max_history_messages
        )
        trace.emit(
            "history",
            "history_loaded",
            metadata={
                "message_count": len(history),
                "last_role": history[-1]["role"] if history else None,
                "ordering": "oldest_to_newest",
            },
        )
        self.repository.save_message(tenant_id, session_id, "user", message.strip())
        trace.emit(
            "query",
            "query_normalized",
            metadata={
                "normalized_length": len(message.strip()),
                "language_hint": (
                    "Hindi/Hinglish"
                    if any(ord(char) > 127 for char in message)
                    else "Latin"
                ),
            },
            content=message.strip(),
        )

        if on_progress:
            on_progress("understanding")
        decision = await self.router.route(
            message.strip(),
            history,
            {
                "assistant_name": identity.assistant_name,
                "business_name": identity.business_name,
                "assistant_description": identity.description,
                "identity_instructions": identity.instructions,
            },
            trace=trace,
        )
        trace.emit(
            "router",
            "route_selected",
            metadata={
                "route": decision.route.value,
                "confidence": decision.confidence,
                "retrieval_query_present": bool(decision.retrieval_query),
                "resolved_query_present": bool(decision.resolved_query),
                "clarification": bool(decision.clarifying_question),
            },
        )
        citations: list[Citation] = []
        evidence_status: str | None = None

        if decision.route == RouteName.CLARIFICATION_REQUIRED:
            answer = decision.clarifying_question or "What are you referring to?"
            trace.emit(
                "answer",
                "clarification_returned",
                metadata={"answer_length": len(answer)},
            )
        elif decision.route == RouteName.GENERAL_CONVERSATION:
            # Architectural invariant: general/identity turns never retrieve or ground.
            effective_message = decision.resolved_query or message.strip()
            smalltalk_answer = deterministic_smalltalk_response(effective_message)
            if smalltalk_answer:
                answer = smalltalk_answer
                trace.emit(
                    "answer",
                    "smalltalk_answered",
                    metadata={"deterministic": True, "provider_call": False},
                )
            elif is_identity_question(effective_message, identity):
                answer = identity_response(effective_message, identity)
                trace.emit(
                    "answer",
                    "identity_answered",
                    metadata={
                        "deterministic": True,
                        "assistant_name": identity.assistant_name,
                        "provider_call": False,
                    },
                )
            else:
                if on_progress:
                    on_progress("generating")
                trace.emit(
                    "answer",
                    "generation_started",
                    metadata={
                        **self._provider_meta(),
                        "history_count": len(history),
                        "evidence_count": 0,
                    },
                )
                generator_args = (effective_message, history, client["prompt"], identity_context)
                if on_token:
                    generator_args = (*generator_args, on_token)
                answer = await self.generator.general(*generator_args)
                trace.emit(
                    "answer",
                    "generation_completed",
                    metadata={"answer_length": len(answer)},
                )
        else:
            if on_progress:
                on_progress("retrieving")
            retrieval_query = (
                decision.retrieval_query or decision.resolved_query or message.strip()
            )
            trace.emit(
                "retrieval",
                "retrieval_started",
                metadata={
                    "provider": getattr(self.settings, "embedding_provider", None),
                    "model": getattr(self.settings, "embedding_model", None),
                    "dimension": getattr(
                        getattr(self.retriever, "embeddings", None), "dimension", None
                    ),
                    "tenant_filter": tenant_id,
                    "top_k": self.settings.rag_top_k,
                    "query_length": len(retrieval_query),
                },
                content=retrieval_query,
            )
            retrieval = await self.retriever.retrieve(tenant_id, retrieval_query)
            trace.emit(
                "retrieval",
                "retrieval_completed",
                metadata={
                    "chunk_count": len(retrieval.chunks),
                    "source_ids": [item.get("source_id") for item in retrieval.chunks],
                    "similarities": [
                        round(float(item.get("similarity", 0)), 4)
                        for item in retrieval.chunks
                    ],
                    "context_length": len(retrieval.context),
                },
            )
            if not retrieval.chunks and decision.route == RouteName.BUSINESS_KNOWLEDGE:
                answer, evidence_status = (
                    "I don’t have relevant business information indexed for that yet.",
                    EvidenceStatus.INSUFFICIENT.value,
                )
                trace.emit(
                    "evidence", "evidence_insufficient", metadata={"chunk_count": 0}
                )
            elif not retrieval.chunks:
                evidence_status = EvidenceStatus.INSUFFICIENT.value
                if on_progress:
                    on_progress("generating")
                generator_args = (
                    message
                    + "\nExplain only the general part and say the business-specific part cannot be confirmed.",
                    history,
                    client["prompt"],
                    identity_context,
                )
                if on_token:
                    generator_args = (*generator_args, on_token)
                answer = await self.generator.general(*generator_args)
                trace.emit(
                    "evidence",
                    "evidence_insufficient_general_part",
                    metadata={"chunk_count": 0},
                )
            else:
                if on_progress:
                    on_progress("checking_evidence")
                trace.emit(
                    "evidence",
                    "evaluation_started",
                    metadata={
                        "chunk_count": len(retrieval.chunks),
                        "context_length": len(retrieval.context),
                    },
                )
                evaluation = await self.evaluator.evaluate(
                    message, retrieval.context, retrieval.chunks, history, trace
                )
                evidence_status = evaluation.status.value

                trace.emit(
                    "evidence",
                    "evaluation_completed",
                    metadata={
                        "status": evidence_status,
                        "available": evaluation.available,
                        "supported_aspects": evaluation.supported_aspects,
                        "missing_aspects": evaluation.missing_aspects,
                        "conflicts": evaluation.conflicts,
                    },
                )

                if not evaluation.available:
                    # Retrieved tenant-scoped documents remain usable when the
                    # optional evidence evaluator is temporarily rate-limited.
                    # Continue in partial mode and still run answer grounding.
                    evaluation.status = EvidenceStatus.PARTIAL
                    evidence_status = EvidenceStatus.PARTIAL.value
                    trace.emit(
                        "evidence",
                        "evaluation_unavailable_continue_with_retrieved_context",
                        status="warning",
                        metadata={"chunk_count": len(retrieval.chunks)},
                    )

                if on_progress:
                    on_progress("generating")
                trace.emit(
                    "answer",
                    "generation_started",
                    metadata={
                        **self._provider_meta(),
                        "history_count": len(history),
                        "evidence_count": len(retrieval.chunks),
                        "context_length": len(retrieval.context),
                    },
                )

                answer = await self.generator.with_evidence(
                    message,
                    history,
                    retrieval.context,
                    evidence_status,
                    client["prompt"],
                    identity_context,
                )

                trace.emit(
                    "answer",
                    "generation_completed",
                    metadata={"answer_length": len(answer)},
                )

                valid_ids = {chunk["source_id"] for chunk in retrieval.chunks}

                if on_progress:
                    on_progress("verifying")
                trace.emit(
                    "grounding",
                    "verification_started",
                    metadata={
                        "valid_source_ids": sorted(valid_ids),
                        "answer_length": len(answer),
                    },
                )

                verification = await self.verifier.verify(
                    message,
                    answer,
                    retrieval.context,
                    valid_ids,
                    history,
                    trace,
                )

                trace.emit(
                    "grounding",
                    "verification_completed",
                    metadata={
                        "status": verification.status.value,
                        "available": verification.available,
                        "supported_source_ids": verification.supported_source_ids,
                        "unsupported_count": len(verification.unsupported_claims),
                        "contradicted_count": len(verification.contradicted_claims),
                    },
                )

                if not verification.available:
                    # A verifier outage (often a provider TPM/429 limit)
                    # must not discard a usable, source-cited answer when
                    # retrieval and evidence coverage are adequate.
                    cited_ids = set(re.findall(r"\[(S\d+)\]", answer))
                    allowed_ids = cited_ids.intersection(valid_ids)
                    citations = self._citations(retrieval.chunks, allowed_ids)

                    if (
                        evaluation.status == EvidenceStatus.SUFFICIENT
                        and citations
                        and answer_is_lexically_supported(
                            answer,
                            retrieval.chunks,
                            valid_ids,
                        )
                    ):
                        trace.emit(
                            "grounding",
                            "verification_unavailable_citation_check_passed",
                            status="warning",
                            metadata={
                                "provider": self._provider_meta().get("provider"),
                                "citation_count": len(citations),
                                "evidence_status": evaluation.status.value,
                            },
                        )
                    else:
                        answer, citations = self._fallback(
                            retrieval.chunks,
                            evaluation.status == EvidenceStatus.CONFLICTING,
                        )
                        trace.emit(
                            "final_response",
                            "safe_fallback_selected",
                            status="warning",
                            metadata={
                                "reason": "verification_unavailable_without_sufficient_cited_evidence",
                                "citation_count": len(citations),
                            },
                        )

                else:
                    needs_correction = verification.status in {
                        GroundingStatus.UNSUPPORTED,
                        GroundingStatus.CONTRADICTED,
                    } or bool(
                        verification.unsupported_claims
                        or verification.contradicted_claims
                    )

                    if needs_correction:
                        if on_progress:
                            on_progress("correcting")
                        trace.emit(
                            "correction",
                            "correction_started",
                            metadata={
                                "attempt": 1,
                                "reason": verification.reason[:300],
                            },
                        )

                        try:
                            corrected = await self.generator.correct(
                                message,
                                answer,
                                verification.unsupported_claims,
                                verification.contradicted_claims,
                                retrieval.context,
                                history,
                                client["prompt"],
                                identity_context,
                            )

                            second = await self.verifier.verify(
                                message,
                                corrected,
                                retrieval.context,
                                valid_ids,
                                history,
                                trace,
                            )

                            trace.emit(
                                "correction",
                                "correction_completed",
                                metadata={
                                    "attempts": 1,
                                    "verification_status": second.status.value,
                                    "verification_available": second.available,
                                },
                            )

                        except Exception as exc:
                            corrected = ""
                            second = None

                            trace.emit(
                                "correction",
                                "correction_failed",
                                status="error",
                                error=exc,
                                metadata={"attempts": 1},
                            )

                        if second is None or not second.available:
                            answer = (
                                "I'm temporarily unable to complete "
                                "answer verification. Please try again shortly."
                            )
                            citations = []

                        elif (
                            second.status
                            in {
                                GroundingStatus.SUPPORTED,
                                GroundingStatus.PARTIALLY_SUPPORTED,
                            }
                            and second.supported_source_ids
                            and not second.unsupported_claims
                            and not second.contradicted_claims
                        ):
                            answer = corrected
                            verification = second

                        else:
                            answer, citations = self._fallback(
                                retrieval.chunks,
                                evaluation.status == EvidenceStatus.CONFLICTING,
                            )

                            trace.emit(
                                "final_response",
                                "safe_fallback_selected",
                                metadata={
                                    "reason": "grounding_not_verified",
                                    "citation_count": len(citations),
                                },
                            )

                    if verification.available and not citations:
                        # Grounding-approved source IDs are authoritative.
                        # Do not require them to match labels independently
                        # generated by the answer model.
                        allowed = set(verification.supported_source_ids).intersection(
                            valid_ids
                        )

                        answer, citations = self._apply_verified_citations(
                            answer,
                            retrieval.chunks,
                            allowed,
                        )

                        if not citations:
                            answer, citations = self._fallback(
                                retrieval.chunks,
                                evaluation.status == EvidenceStatus.CONFLICTING,
                            )

                            trace.emit(
                                "final_response",
                                "safe_fallback_selected",
                                metadata={
                                    "reason": "no_verifier_approved_citations",
                                    "citation_count": len(citations),
                                },
                            )

        if on_progress:
            on_progress("saving")
        self.repository.save_message(
            tenant_id,
            session_id,
            "assistant",
            answer,
            [item.model_dump() for item in citations],
            decision.route.value,
            evidence_status,
        )
        self.repository.usage(
            tenant_id, decision.route.value, (time.perf_counter() - started) * 1000
        )
        trace.emit(
            "persistence",
            "conversation_saved",
            metadata={"session_id": session_id, "citation_count": len(citations)},
        )
        return {
            "session_id": session_id,
            "request_id": request_id,
            "answer": answer,
            "citations": citations,
            "route": decision.route.value,
            "evidence_status": evidence_status,
        }
