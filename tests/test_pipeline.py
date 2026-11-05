from __future__ import annotations

import pytest

from app.domain.schemas import RouteName
from app.rag.evidence import EvidenceEvaluation, EvidenceStatus
from app.rag.grounding import GroundingDecision, GroundingStatus
from app.rag.pipeline import ChatPipeline
from app.rag.router import IntelligenceRouter


class FakeLLM:
    def __init__(self, outputs: list[str] | None = None):
        self.outputs = list(outputs or [])
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def complete(self, role, messages, **kwargs):
        self.calls.append((role, messages))
        if not self.outputs:
            return "general answer"
        return self.outputs.pop(0)


class FakeEmbeddings:
    dimension = 3
    fingerprint = "test:embeddings:3"

    async def embed_query(self, text):
        return [1.0, 0.0, 0.0]

    async def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FailRetriever:
    def __init__(self):
        self.called = False

    async def retrieve(self, tenant_id, query):
        self.called = True
        raise AssertionError("general/clarification branch must not retrieve")


class FakeRetriever:
    def __init__(self):
        self.called = 0

    async def retrieve(self, tenant_id, query):
        self.called += 1
        from app.rag.retrieval import RetrievalResult
        return RetrievalResult([{"source_id": "S1", "text": "The price is 10", "similarity": .9, "metadata": {"source_filename": "a.md"}}], "[S1] source=a.md\nThe price is 10")


class FakeEvaluator:
    async def evaluate(self, *args):
        return EvidenceEvaluation(status=EvidenceStatus.SUFFICIENT, supported_aspects=["price"])


class FakeGenerator:
    def __init__(self):
        self.general_calls = 0
        self.evidence_calls = 0
        self.correction_calls = 0

    async def general(self, *args):
        self.general_calls += 1
        return "general answer"

    async def with_evidence(self, *args):
        self.evidence_calls += 1
        return "The price is 10 [S1]"

    async def correct(self, *args):
        self.correction_calls += 1
        return "The price is 10 [S1]"


class FakeVerifier:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = 0

    async def verify(self, *args):
        self.calls += 1
        return next(self.decisions)


@pytest.mark.asyncio
async def test_general_fast_path_bypasses_retrieval(settings, repository):
    tenant = repository.create_client("A", "general-a", ["https://a.example"], {}, "prompt")
    llm = FakeLLM()
    retriever = FailRetriever()
    generator = FakeGenerator()
    pipeline = ChatPipeline(settings, repository, IntelligenceRouter(llm, settings), retriever, FakeEvaluator(), generator, FakeVerifier([]))
    result = await pipeline.handle(tenant["id"], "hey bro", None, "request-1")
    assert result["route"] == RouteName.GENERAL_CONVERSATION
    assert not retriever.called
    assert generator.general_calls == 0
    assert llm.calls == []
    assert result['answer'] == 'Hey! How can I help you today?'


@pytest.mark.asyncio
async def test_clarification_does_not_retrieve(settings, repository):
    tenant = repository.create_client("A", "clarify-a", ["https://a.example"], {}, "prompt")
    retriever = FailRetriever()
    pipeline = ChatPipeline(settings, repository, IntelligenceRouter(FakeLLM(), settings), retriever, FakeEvaluator(), FakeGenerator(), FakeVerifier([]))
    result = await pipeline.handle(tenant["id"], "what about the price?", None, "request-2")
    assert result["route"] == RouteName.CLARIFICATION_REQUIRED
    assert not retriever.called


@pytest.mark.asyncio
async def test_business_correction_is_exactly_one_and_filters_fake_ids(settings, repository):
    tenant = repository.create_client("A", "business-a", ["https://a.example"], {}, "prompt")
    retriever = FakeRetriever(); generator = FakeGenerator()
    verifier = FakeVerifier([
        GroundingDecision(status=GroundingStatus.UNSUPPORTED, supported_source_ids=["S999"], unsupported_claims=["bad"]),
        GroundingDecision(status=GroundingStatus.SUPPORTED, supported_source_ids=["S1"]),
    ])
    pipeline = ChatPipeline(settings, repository, IntelligenceRouter(FakeLLM(["business"]), settings), retriever, FakeEvaluator(), generator, verifier)
    result = await pipeline.handle(tenant["id"], "what is your pricing?", None, "request-3")
    assert retriever.called == 1
    assert generator.correction_calls == 1
    assert verifier.calls == 2
    assert [citation.source_id for citation in result["citations"]] == ["S1"]


@pytest.mark.asyncio
async def test_verifier_rate_limit_keeps_sufficient_answer_with_valid_citations(settings, repository):
    tenant = repository.create_client("A", "business-verifier-outage", ["https://a.example"], {}, "prompt")
    unavailable = GroundingDecision(
        status=GroundingStatus.UNSUPPORTED,
        reason="Verifier provider unavailable",
        available=False,
    )
    retriever = FakeRetriever()
    generator = FakeGenerator()
    verifier = FakeVerifier([unavailable])
    pipeline = ChatPipeline(
        settings,
        repository,
        IntelligenceRouter(FakeLLM(), settings),
        retriever,
        FakeEvaluator(),
        generator,
        verifier,
    )

    result = await pipeline.handle(
        tenant["id"],
        "what is your pricing?",
        None,
        "request-verifier-unavailable",
    )

    assert result["answer"] == "The price is 10 [S1]"
    assert [citation.source_id for citation in result["citations"]] == ["S1"]
    assert verifier.calls == 1


@pytest.mark.asyncio
async def test_legacy_evaluator_outage_does_not_bypass_deterministic_sufficiency_gate(settings, repository):
    tenant = repository.create_client("A", "business-evaluator-outage", ["https://a.example"], {}, "prompt")

    class UnavailableEvaluator:
        async def evaluate(self, *args):
            return EvidenceEvaluation(
                status=EvidenceStatus.INSUFFICIENT,
                reason="Evaluator provider unavailable",
                available=False,
            )

    retriever = FakeRetriever()
    generator = FakeGenerator()
    verifier = FakeVerifier([
        GroundingDecision(
            status=GroundingStatus.UNSUPPORTED,
            reason="Verifier provider unavailable",
            available=False,
        )
    ])
    pipeline = ChatPipeline(
        settings,
        repository,
        IntelligenceRouter(FakeLLM(), settings),
        retriever,
        UnavailableEvaluator(),
        generator,
        verifier,
    )

    result = await pipeline.handle(
        tenant["id"],
        "what is your pricing?",
        None,
        "request-evaluator-unavailable",
    )

    assert generator.evidence_calls == 1
    assert result["answer"].startswith("I found related information in the business documents")
    assert result["evidence_status"] == EvidenceStatus.PARTIAL.value
    assert [citation.source_id for citation in result["citations"]] == ["S1"]


@pytest.mark.asyncio
async def test_evidence_evaluation_uses_local_coverage_without_llm_calls():
    from app.rag.evidence import EvidenceEvaluator

    class NoCall:
        async def complete(self, *args, **kwargs):
            raise AssertionError("deterministic evidence evaluation must not call an LLM")

    evaluator = EvidenceEvaluator(NoCall())
    chunks = [{
        "source_id": "S1",
        "text": "One-time setup fee is $199 and includes the first month. After that, the ongoing fee is $49 per month.",
        "similarity": 0.91,
    }]
    result = await evaluator.evaluate(
        "What is the total setup cost, and what do I pay after the first month?",
        "[S1] " + chunks[0]["text"],
        chunks,
        [],
    )
    assert result.status == EvidenceStatus.SUFFICIENT
    assert result.available is True


@pytest.mark.asyncio
async def test_outage_answer_gate_requires_matching_numbers_and_citations():
    from app.rag.evidence import answer_is_lexically_supported

    chunks = [{
        "source_id": "S1",
        "text": "One-time setup fee is $199 and includes the first month. After that, the ongoing fee is $49 per month.",
    }]
    valid_ids = {"S1"}
    grounded = "Setup fee is $199. After the first month, it is $49 per month. [S1]"
    wrong_amount = "Setup fee is $299. After the first month, it is $49 per month. [S1]"
    assert answer_is_lexically_supported(grounded, chunks, valid_ids)
    assert not answer_is_lexically_supported(wrong_amount, chunks, valid_ids)
    assert not answer_is_lexically_supported("Setup fee is $199.", chunks, valid_ids)


def test_router_handles_setup_pricing_and_standalone_greetings_without_router_llm(settings):
    from app.rag.router import deterministic_route, deterministic_smalltalk_response

    pricing = deterministic_route(
        "What is the total setup cost, and what do I pay after the first month?",
        [],
    )
    assert pricing is not None
    assert pricing.route == RouteName.BUSINESS_KNOWLEDGE
    assert deterministic_smalltalk_response("hey bro") == "Hey! How can I help you today?"


@pytest.mark.asyncio
async def test_supported_verification_without_source_ids_skips_unneeded_correction(settings, repository):
    tenant = repository.create_client("A", "missing-source-id", ["https://a.example"], {}, "prompt")
    retriever = FakeRetriever()
    generator = FakeGenerator()
    verifier = FakeVerifier([
        GroundingDecision(status=GroundingStatus.SUPPORTED, supported_source_ids=[])
    ])
    pipeline = ChatPipeline(
        settings,
        repository,
        IntelligenceRouter(FakeLLM(), settings),
        retriever,
        FakeEvaluator(),
        generator,
        verifier,
    )
    result = await pipeline.handle(
        tenant["id"],
        "what is your pricing?",
        None,
        "request-no-source-id",
    )
    assert generator.correction_calls == 0
    assert verifier.calls == 1
    assert result["answer"].startswith("I found related information in the business documents")
