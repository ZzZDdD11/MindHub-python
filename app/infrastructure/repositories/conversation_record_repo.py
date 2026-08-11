"""Persistence for completed gateway conversation records."""
import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.entities import ConversationRecordEntity
from app.infrastructure.database.connection import get_db

logger = logging.getLogger(__name__)


class ConversationRecordRepository:
    _COLUMNS = (
        "id, request_log_id, trace_id, origin, api_key_id, channel_id, channel_name, model, "
        "upstream_model, protocol_type, stream, request_payload, response_payload, completed_at"
    )

    def get_by_id(self, record_id: str):
        return self._get_one("id = :record_id", {"record_id": record_id})

    def get_by_request_log_id(self, request_log_id: str):
        return self._get_one("request_log_id = :request_log_id", {"request_log_id": request_log_id})

    def create_if_absent(self, record: ConversationRecordEntity) -> ConversationRecordEntity:
        try:
            with get_db() as db:
                db.execute(text(
                    "INSERT INTO conversation_records ("
                    "id, request_log_id, trace_id, origin, api_key_id, channel_id, channel_name, "
                    "model, upstream_model, protocol_type, stream, request_payload, response_payload, completed_at"
                    ") VALUES ("
                    ":id, :request_log_id, :trace_id, :origin, :api_key_id, :channel_id, :channel_name, "
                    ":model, :upstream_model, :protocol_type, :stream, :request_payload, :response_payload, :completed_at"
                    ")"
                ), {
                    "id": record.id,
                    "request_log_id": record.request_log_id,
                    "trace_id": record.trace_id,
                    "origin": record.origin,
                    "api_key_id": record.api_key_id,
                    "channel_id": record.channel_id,
                    "channel_name": record.channel_name,
                    "model": record.model,
                    "upstream_model": record.upstream_model,
                    "protocol_type": record.protocol_type,
                    "stream": 1 if record.stream else 0,
                    "request_payload": record.request_payload,
                    "response_payload": record.response_payload,
                    "completed_at": record.completed_at,
                })
            return record
        except IntegrityError:
            logger.info("Conversation record already exists for request_log_id=%s", record.request_log_id)
            existing = self.get_by_request_log_id(record.request_log_id)
            if existing:
                return existing
            raise

    def _get_one(self, where_clause: str, params: dict):
        with get_db() as db:
            row = db.execute(text(
                f"SELECT {self._COLUMNS} FROM conversation_records WHERE {where_clause}"
            ), params).mappings().first()
        return self._to_entity(row) if row else None

    @classmethod
    def _to_entity(cls, row) -> ConversationRecordEntity:
        return ConversationRecordEntity(
            id=row["id"],
            request_log_id=row["request_log_id"],
            trace_id=row["trace_id"],
            origin=row["origin"],
            api_key_id=row["api_key_id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            model=row["model"],
            upstream_model=row["upstream_model"],
            protocol_type=row["protocol_type"],
            stream=bool(row["stream"]),
            request_payload=row["request_payload"],
            response_payload=row["response_payload"],
            completed_at=row["completed_at"],
        )
