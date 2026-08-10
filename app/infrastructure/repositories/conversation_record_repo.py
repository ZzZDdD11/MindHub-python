"""Persistence for completed gateway conversation records."""
import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.entities import ConversationRecordEntity
from app.infrastructure.database.connection import get_db

logger = logging.getLogger(__name__)


class ConversationRecordRepository:
    def create_if_absent(self, record: ConversationRecordEntity) -> bool:
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
            return True
        except IntegrityError:
            logger.info("Conversation record already exists for request_log_id=%s", record.request_log_id)
            return False
