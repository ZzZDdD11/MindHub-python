"""Persistence for pending conversation candidates."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.entities import ConversationCandidateEntity
from app.infrastructure.database.connection import get_db


class ConversationCandidateRepository:
    _COLUMNS = (
        "id, conversation_record_id, status, eligibility_policy_version, created_at, updated_at"
    )

    def get_by_conversation_record_id(self, conversation_record_id: str):
        with get_db() as db:
            row = db.execute(text(
                f"SELECT {self._COLUMNS} FROM conversation_candidates "
                "WHERE conversation_record_id = :conversation_record_id"
            ), {"conversation_record_id": conversation_record_id}).mappings().first()
        return self._to_entity(row) if row else None

    def create_if_absent(self, candidate: ConversationCandidateEntity) -> ConversationCandidateEntity:
        try:
            with get_db() as db:
                db.execute(text(
                    "INSERT INTO conversation_candidates ("
                    "id, conversation_record_id, status, eligibility_policy_version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :conversation_record_id, :status, :eligibility_policy_version, :created_at, :updated_at"
                    ")"
                ), {
                    "id": candidate.id,
                    "conversation_record_id": candidate.conversation_record_id,
                    "status": candidate.status,
                    "eligibility_policy_version": candidate.eligibility_policy_version,
                    "created_at": candidate.created_at,
                    "updated_at": candidate.updated_at,
                })
            return candidate
        except IntegrityError:
            existing = self.get_by_conversation_record_id(candidate.conversation_record_id)
            if existing:
                return existing
            raise

    @classmethod
    def _to_entity(cls, row) -> ConversationCandidateEntity:
        return ConversationCandidateEntity(
            id=row["id"],
            conversation_record_id=row["conversation_record_id"],
            status=row["status"],
            eligibility_policy_version=row["eligibility_policy_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
