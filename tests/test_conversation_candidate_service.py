from app.application.services.conversation_candidate_service import ConversationCandidateService
from app.domain.entities import ConversationRecordEntity


class FakeConversationRecordRepository:
    def __init__(self, records=()):
        self.records = {record.id: record for record in records}

    def get_by_id(self, record_id):
        return self.records.get(record_id)


class FakeConversationCandidateRepository:
    def __init__(self):
        self.candidates = {}

    def create_if_absent(self, candidate):
        return self.candidates.setdefault(candidate.conversation_record_id, candidate)


def record(record_id="record-123"):
    return ConversationRecordEntity(
        id=record_id,
        request_log_id="log-123",
        trace_id="trace-123",
        origin="external",
        model="gpt-4o",
        protocol_type="openai",
        stream=False,
        request_payload='{"messages":[{"role":"user","content":"hello"}]}',
        response_payload='{"choices":[{"message":{"content":"done"}}]}',
        completed_at="2026-08-11 10:00:00",
    )


def test_enqueue_from_completed_record_creates_pending_candidate() -> None:
    source = record()
    candidate_repo = FakeConversationCandidateRepository()
    service = ConversationCandidateService(
        FakeConversationRecordRepository([source]), candidate_repo,
    )

    candidate = service.enqueue_from_completed_record(source.id)

    assert candidate.conversation_record_id == source.id
    assert candidate.status == "pending_review"
    assert candidate.eligibility_policy_version == "completed-conversation-v1"
    assert len(candidate_repo.candidates) == 1
    assert set(vars(candidate)) == {
        "id", "conversation_record_id", "status", "eligibility_policy_version", "created_at", "updated_at",
    }


def test_enqueue_is_idempotent_and_unknown_source_is_ignored() -> None:
    source = record()
    candidate_repo = FakeConversationCandidateRepository()
    service = ConversationCandidateService(
        FakeConversationRecordRepository([source]), candidate_repo,
    )

    first = service.enqueue_from_completed_record(source.id)
    second = service.enqueue_from_completed_record(source.id)

    assert second is first
    assert len(candidate_repo.candidates) == 1
    assert service.enqueue_from_completed_record("missing-record") is None
