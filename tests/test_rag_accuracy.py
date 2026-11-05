from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.schemas import RouteName
from app.rag.evidence import EvidenceEvaluation, EvidenceStatus
from app.rag.grounding import GroundingDecision, GroundingStatus
from app.rag.identity import resolve_identity
from app.rag.pipeline import ChatPipeline
from app.rag.router import IntelligenceRouter, deterministic_route


class NoCallLLM:
    async def complete(self, *args, **kwargs):
        raise AssertionError("the deterministic route should not call the router for this input")


class GeneralLLM:
    def __init__(self):
        self.calls = []

    async def complete(self, role, messages, **kwargs):
        self.calls.append((role, messages, kwargs))
        return "A direct answer."


class RetrievalSpy:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    async def retrieve(self, tenant_id, query):
        self.queries.append((tenant_id, query))
        from app.rag.retrieval import RetrievalResult
        return RetrievalResult(self.chunks, "\n".join(f"[{item['source_id']}] {item['text']}" for item in self.chunks))


class EvidenceSpy:
    async def evaluate(self, *args):
        return EvidenceEvaluation(status=EvidenceStatus.SUFFICIENT, supported_aspects=["identity"])


class GroundingSpy:
    async def verify(self, *args):
        return GroundingDecision(status=GroundingStatus.SUPPORTED, supported_source_ids=["S1"])


class GeneratorSpy:
    def __init__(self):
        self.general = []
        self.evidence = []

    async def general(self, *args):
        self.general.append(args)
        return "General response."

    async def with_evidence(self, *args):
        self.evidence.append(args)
        return "AttachAI is a personalized AI assistant service. [S1]"

    async def correct(self, *args):
        return "AttachAI is a personalized AI assistant service. [S1]"


def _client(repository, name, slug, assistant_name):
    return repository.create_client(name, slug, [f"https://{slug}.example"], {"assistantName": assistant_name, "businessName": name}, "Tenant prompt")


@pytest.mark.asyncio
async def test_identity_questions_are_tenant_specific_and_do_not_leak_provider(settings, repository):
    tenant_a = _client(repository, "AttachAI", "attachai", "AttachAI Assistant")
    tenant_b = _client(repository, "North Star", "north-star", "North Star Helper")
    for tenant, message, expected in ((tenant_a, "aap koun ho", "AttachAI Assistant"), (tenant_a, "what is your name", "AttachAI Assistant"), (tenant_b, "what is your name", "North Star Helper")):
        pipeline = ChatPipeline(settings, repository, IntelligenceRouter(NoCallLLM(), settings), RetrievalSpy([]), EvidenceSpy(), GeneratorSpy(), GroundingSpy())
        result = await pipeline.handle(tenant["id"], message, None, f"identity-{slugify(message)}")
        assert result["route"] == RouteName.GENERAL_CONVERSATION
        assert expected in result["answer"]
        assert "ChatGPT" not in result["answer"]
        assert "OpenAI" not in result["answer"]


def slugify(value):
    return "".join(char for char in value if char.isalnum())


def test_reference_router_identity_and_business_identity_routes(settings):
    identity = resolve_identity({"name": "AttachAI", "config": {"assistantName": "AttachAI Assistant"}})
    assert deterministic_route("aap koun ho", [], identity).route == RouteName.GENERAL_CONVERSATION
    assert deterministic_route("what is your name", [], identity).route == RouteName.GENERAL_CONVERSATION
    business = deterministic_route("who is this AttachAI", [], identity)
    assert business.route == RouteName.BUSINESS_KNOWLEDGE
    assert business.requires_rag


def test_reference_attachai_fixture_contains_expected_grounding_facts():
    corpus = (Path(__file__).parent / "fixtures" / "AttachAI-Assistant-Structured-Knowledge-Base-Updated.md").read_text(encoding="utf-8").casefold()
    assert "personalized ai assistant" in corpus
    assert "mahesh editor" in corpus
    assert "hata, uttar pradesh 274203" in corpus


def test_pending_clarification_business_reply_resolves_previous_question(settings):
    history = [
        {"role": "user", "content": "Who is this business?"},
        {"role": "assistant", "content": "Is your question about this business, or is it a general question?"},
    ]
    decision = deterministic_route("business", history)
    assert decision.route == RouteName.BUSINESS_KNOWLEDGE
    assert decision.retrieval_query == "Who is this business?"
    assert decision.clarifying_question is None


@pytest.mark.asyncio
async def test_business_identity_retrieves_evaluates_and_cites(settings, repository):
    tenant = _client(repository, "AttachAI", "attachai-business", "AttachAI Assistant")
    chunks = [{"source_id": "S1", "text": "AttachAI is a personalized AI assistant service for business websites.", "similarity": .92, "metadata": {"source_filename": "AttachAI-Assistant-Structured-Knowledge-Base-Updated.md"}}]
    retriever = RetrievalSpy(chunks)
    pipeline = ChatPipeline(settings, repository, IntelligenceRouter(NoCallLLM(), settings), retriever, EvidenceSpy(), GeneratorSpy(), GroundingSpy())
    result = await pipeline.handle(tenant["id"], "who is this AttachAI", None, "business-identity")
    assert result["route"] == RouteName.BUSINESS_KNOWLEDGE
    assert retriever.queries[0][1] == "who is this AttachAI"
    assert result["citations"][0].source_id == "S1"
    assert "AttachAI" in result["answer"]


@pytest.mark.asyncio
async def test_trace_contains_end_to_end_stages_without_content_by_default(settings, repository, tmp_path):
    settings.orbit_trace_debug = True
    settings.orbit_trace_log_path = tmp_path / "logs" / "trace.jsonl"
    tenant = _client(repository, "Trace Tenant", "trace-tenant", "Trace Assistant")
    pipeline = ChatPipeline(settings, repository, IntelligenceRouter(NoCallLLM(), settings), RetrievalSpy([]), EvidenceSpy(), GeneratorSpy(), GroundingSpy())
    await pipeline.handle(tenant["id"], "what is your name", None, "trace-request")
    records = [json.loads(line) for line in settings.orbit_trace_log_path.read_text(encoding="utf-8").splitlines()]
    assert records
    assert {item["trace_id"] for item in records} == {"trace-request"}
    assert {item["stage"] for item in records} >= {"request", "identity", "history", "router", "answer", "persistence", "final_response"}
    assert all("content" not in item for item in records)


def test_attachai_service_questions_use_business_knowledge_route(settings):
    # The demo tenant label can differ from the business described in its corpus.
    identity = resolve_identity({
        "name": "BluePeak",
        "config": {"assistantName": "Assistant", "businessName": "BluePeak"},
    })
    decision = deterministic_route(
        "What is AttachAI Assistant, and what services do you provide?",
        [],
        identity,
    )
    assert decision.route == RouteName.BUSINESS_KNOWLEDGE
    assert decision.requires_rag
    assert decision.retrieval_query == "What is AttachAI Assistant, and what services do you provide?"


@pytest.mark.parametrize(
    "question",
    [
        "Explain the difference between the private internal setup system and the website assistant.",
        "Can I install the same client-specific key on multiple websites?",
        "I heard there is a free lifetime plan. Is that correct?",
        "Is Mahesh Editor currently living in the USA? Give verified evidence.",
        "What information about AttachAI is confirmed, and what information is unknown?",
        "If the documents do not contain an answer, can you distinguish facts and assumptions?",
    ],
)
def test_attachai_edge_questions_use_business_knowledge_route(settings, question):
    identity = resolve_identity({
        "name": "BluePeak",
        "config": {"assistantName": "Assistant", "businessName": "BluePeak"},
    })
    decision = deterministic_route(question, [], identity)
    assert decision is not None
    assert decision.route == RouteName.BUSINESS_KNOWLEDGE
    assert decision.requires_rag
    assert decision.requires_grounding


def test_default_history_limit_covers_twenty_user_assistant_exchanges():
    from app.config import Settings

    settings = Settings(_env_file=None, APP_ENV="test")
    assert settings.max_history_messages == 40
