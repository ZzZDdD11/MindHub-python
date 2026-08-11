from types import SimpleNamespace

import pytest

from app.domain.entities import ConversationCandidateEntity, ConversationRecordEntity


class FakeLifecycleRepository:
    def __init__(self, candidate, record):
        self.candidate = candidate
        self.record = record
        self.drafts = {}
        self.cards = {}
        self.versions = {}
        self.projections = {}
        self.wikis = {}
        self.graph_nodes = {}
        self.graph_edges = []

    def get_candidate(self, candidate_id):
        return self.candidate if candidate_id == self.candidate.id else None

    def get_candidate_detail(self, candidate_id):
        if candidate_id != self.candidate.id:
            return None
        return {"candidate": self.candidate, "record": self.record}

    def review_candidate(self, candidate_id, status, note, reviewed_at):
        if candidate_id != self.candidate.id or self.candidate.status != "pending_review":
            return False
        self.candidate.status = status
        self.candidate.review_note = note
        self.candidate.reviewed_at = reviewed_at
        return True

    def get_draft_by_candidate_id(self, candidate_id):
        drafts = [draft for draft in self.drafts.values() if draft.candidate_id == candidate_id]
        return max(drafts, key=lambda draft: draft.revision) if drafts else None

    def next_draft_revision(self, candidate_id):
        draft = self.get_draft_by_candidate_id(candidate_id)
        return draft.revision + 1 if draft else 1

    def get_draft(self, draft_id):
        return self.drafts.get(draft_id)

    def save_draft(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def update_draft(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def get_or_create_card(self, candidate_id, now):
        card = next((item for item in self.cards.values() if item.candidate_id == candidate_id), None)
        if card:
            return card
        from app.domain.entities import KnowledgeCardEntity
        card = KnowledgeCardEntity(id=f"card-{candidate_id}", candidate_id=candidate_id, status="draft", current_version=0, created_at=now, updated_at=now)
        self.cards[card.id] = card
        return card

    def next_card_version(self, card_id):
        return sum(1 for version in self.versions.values() if version.card_id == card_id) + 1

    def save_card_version(self, version):
        self.versions[version.id] = version
        return version

    def get_card_version(self, version_id):
        return self.versions.get(version_id)

    def get_card_version_by_source_draft_id(self, draft_id):
        return next((version for version in self.versions.values() if version.source_draft_id == draft_id), None)

    def update_card_published(self, card_id, version, now):
        card = self.cards[card_id]
        card.status = "published"
        card.current_version = max(card.current_version, version)
        card.updated_at = now
        return card

    def get_projection(self, card_version_id, projection_type):
        return self.projections.get((card_version_id, projection_type))

    def save_projection(self, projection):
        self.projections[(projection.card_version_id, projection.projection_type)] = projection
        return projection

    def get_wiki_by_card_version_id(self, version_id):
        return self.wikis.get(version_id)

    def save_wiki_page(self, page):
        self.wikis[page.card_version_id] = page
        return page

    def get_graph_node(self, kb_id, normalized_name):
        return self.graph_nodes.get((kb_id, normalized_name))

    def upsert_graph_node(self, node):
        self.graph_nodes[(node.kb_id, node.normalized_name)] = node
        return node

    def save_graph_edge_if_absent(self, edge):
        self.graph_edges.append(edge)
        return edge


def source_candidate():
    candidate = ConversationCandidateEntity(
        id="candidate-1", conversation_record_id="record-1", status="pending_review",
        eligibility_policy_version="completed-conversation-v1", created_at="2026-08-11T00:00:00+00:00",
        updated_at="2026-08-11T00:00:00+00:00",
    )
    record = ConversationRecordEntity(
        id="record-1", request_log_id="log-1", trace_id="trace-1", origin="external",
        model="gpt-4o", protocol_type="openai", stream=False,
        request_payload='{"messages":[{"role":"user","content":"Explain request correlation"}]}',
        response_payload='{"choices":[{"message":{"content":"Use a server request ID."}}]}',
        completed_at="2026-08-11T00:00:00+00:00",
    )
    return candidate, record


def service():
    from app.application.services.knowledge_lifecycle_service import KnowledgeLifecycleService
    candidate, record = source_candidate()
    return KnowledgeLifecycleService(FakeLifecycleRepository(candidate, record)), candidate


def test_only_pending_candidate_can_be_reviewed_once():
    lifecycle, candidate = service()

    approved = lifecycle.approve_candidate(candidate.id, "looks useful")

    assert approved.status == "approved"
    assert approved.review_note == "looks useful"
    with pytest.raises(ValueError, match="pending_review"):
        lifecycle.reject_candidate(candidate.id, "second decision")


def test_manual_draft_requires_approved_candidate_and_can_be_published():
    lifecycle, candidate = service()
    with pytest.raises(ValueError, match="approved"):
        lifecycle.create_manual_draft(candidate.id, "Title", "Summary", "Body", ["gateway"])

    lifecycle.approve_candidate(candidate.id, None)
    draft = lifecycle.create_manual_draft(candidate.id, "Request IDs", "Correlation", "Use IDs for tracing.", ["gateway", "trace"])
    published = lifecycle.publish_draft(draft.id, "kb-1")

    assert published["card"].current_version == 1
    assert published["version"].kb_id == "kb-1"
    assert published["wiki"].slug.startswith("request-ids-")
    assert published["projection"].projection_type == "kb_document"
    retried = lifecycle.publish_draft(draft.id, "kb-1")
    assert retried["version"].id == published["version"].id
    assert len(lifecycle.repo.versions) == 1
    revision = lifecycle.create_manual_draft(candidate.id, "Request IDs", "Changed", "Changed", [])
    assert revision.id != draft.id
    assert revision.revision == 2
    second = lifecycle.publish_draft(revision.id, "kb-1")
    assert second["version"].version == 2
    assert second["wiki"].slug != published["wiki"].slug
    assert len(lifecycle.repo.versions) == 2
    old_retry = lifecycle.publish_draft(draft.id, "kb-1")
    assert old_retry["card"].current_version == 2


def test_publication_uses_stable_synchronous_kb_projection():
    from app.application.services.knowledge_lifecycle_service import KnowledgeLifecycleService

    class KbService:
        def __init__(self):
            self.calls = []

        def get_kb(self, kb_id):
            return SimpleNamespace(id=kb_id)

        def import_doc_sync(self, kb_id, dto, document_id):
            self.calls.append((kb_id, dto, document_id))
            return SimpleNamespace(id=document_id)

    candidate, record = source_candidate()
    kb_service = KbService()
    lifecycle = KnowledgeLifecycleService(FakeLifecycleRepository(candidate, record), kb_service=kb_service)
    lifecycle.approve_candidate(candidate.id, None)
    draft = lifecycle.create_manual_draft(candidate.id, "Stable", "Summary", "Content", [])
    published = lifecycle.publish_draft(draft.id, "kb-1")

    assert kb_service.calls[0][0] == "kb-1"
    assert kb_service.calls[0][2] == f"knowledge-card-{published['version'].id}"
    assert published["projection"].external_id == kb_service.calls[0][2]


def test_graph_generation_failure_does_not_make_draft_searchable_in_kb():
    from app.application.services.knowledge_lifecycle_service import KnowledgeLifecycleService
    from app.domain.entities import ProxyResponseEntity

    class KbService:
        def __init__(self):
            self.imports = []

        def get_kb(self, kb_id):
            return SimpleNamespace(id=kb_id)

        def import_doc_sync(self, *args):
            self.imports.append(args)
            return SimpleNamespace(id=args[2])

    class BrokenGraphGateway:
        def forward(self, _):
            return ProxyResponseEntity(status_code=200, body='{"choices":[{"message":{"content":"not-json"}}]}')

    candidate, record = source_candidate()
    repo = FakeLifecycleRepository(candidate, record)
    kb_service = KbService()
    lifecycle = KnowledgeLifecycleService(repo, kb_service, BrokenGraphGateway(), "pipeline-model")
    lifecycle.approve_candidate(candidate.id, None)
    draft = lifecycle.create_manual_draft(candidate.id, "Title", "Summary", "Body", [])

    with pytest.raises(ValueError, match="invalid JSON"):
        lifecycle.publish_draft(draft.id, "kb-1")

    assert kb_service.imports == []
    assert draft.status == "draft"


def test_ai_draft_requires_valid_json_and_never_publishes_automatically():
    from app.application.services.knowledge_lifecycle_service import KnowledgeLifecycleService
    from app.domain.entities import ProxyResponseEntity

    class Gateway:
        def __init__(self, body):
            self.body = body

        def forward(self, _):
            return ProxyResponseEntity(status_code=200, body=self.body)

    candidate, record = source_candidate()
    repo = FakeLifecycleRepository(candidate, record)
    service = KnowledgeLifecycleService(
        repo, gateway_service=Gateway('{"choices":[{"message":{"content":"not-json"}}]}'),
        pipeline_model="pipeline-model",
    )
    service.approve_candidate(candidate.id, None)
    with pytest.raises(ValueError, match="invalid JSON"):
        service.generate_ai_draft(candidate.id)
    assert repo.drafts == {}

    service.gateway = Gateway(
        '{"choices":[{"message":{"content":"{\\\"title\\\":\\\"AI title\\\",\\\"summary\\\":\\\"AI summary\\\",\\\"content\\\":\\\"AI content\\\",\\\"tags\\\":[\\\"ai\\\"],\\\"entities\\\":[],\\\"relations\\\":[]}"}}]}'
    )
    draft = service.generate_ai_draft(candidate.id)
    assert draft.generation_mode == "ai"
    assert draft.status == "draft"
    assert repo.cards == {}


def test_publication_is_rejected_until_a_draft_exists_and_graph_is_scoped_to_kb():
    lifecycle, candidate = service()
    lifecycle.approve_candidate(candidate.id, None)
    with pytest.raises(ValueError, match="Draft not found"):
        lifecycle.publish_draft("missing", "kb-1")

    draft = lifecycle.create_manual_draft(candidate.id, "Graph", "Summary", "Body", [])
    published = lifecycle.publish_draft(draft.id, "kb-1")
    graph = lifecycle.project_graph(published["version"].id, {
        "entities": [{"name": "Request ID", "type": "concept"}],
        "relations": [{"source": "Request ID", "target": "Trace", "type": "relates_to", "evidence": "Body", "confidence": 0.8}],
    })

    assert graph["nodes"][0].kb_id == "kb-1"
    assert graph["edges"][0].source_card_version_id == published["version"].id
    assert graph["edges"][0].confidence == 0.8
    with pytest.raises(ValueError, match="relations"):
        lifecycle.project_graph(published["version"].id, {"entities": [], "relations": {}})
