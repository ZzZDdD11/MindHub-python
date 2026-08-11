"""Application service for projecting completed conversations into review candidates."""
from datetime import datetime, timezone
import uuid

from app.domain.entities import ConversationCandidateEntity, ConversationRecordEntity


class ConversationCandidateService:
    STATUS_PENDING_REVIEW = "pending_review"
    ELIGIBILITY_POLICY_VERSION = "completed-conversation-v1"

    def __init__(self, conversation_record_repository, conversation_candidate_repository):
        self.conversation_record_repo = conversation_record_repository
        self.candidate_repo = conversation_candidate_repository

    def enqueue_from_completed_record(self, conversation_record_id: str):
        record = self.conversation_record_repo.get_by_id(conversation_record_id)
        if not record:
            return None
        return self.enqueue_record(record)

    def enqueue_record(self, record: ConversationRecordEntity) -> ConversationCandidateEntity:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return self.candidate_repo.create_if_absent(ConversationCandidateEntity(
            id=uuid.uuid4().hex,
            conversation_record_id=record.id,
            status=self.STATUS_PENDING_REVIEW,
            eligibility_policy_version=self.ELIGIBILITY_POLICY_VERSION,
            created_at=now,
            updated_at=now,
        ))
