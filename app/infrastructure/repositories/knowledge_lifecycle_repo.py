"""Persistence for administrator-governed knowledge lifecycle data."""
import json
import uuid
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.entities import (
    ConversationCandidateEntity, ConversationRecordEntity, KnowledgeCardEntity,
    KnowledgeCardVersionEntity, KnowledgeDraftEntity, KnowledgeGraphEdgeEntity,
    KnowledgeGraphNodeEntity, KnowledgeProjectionEntity, KnowledgeWikiPageEntity,
)
from app.infrastructure.database.connection import get_db


class KnowledgeLifecycleRepository:
    def list_candidate_details(self, status="pending_review"):
        with get_db() as db:
            rows = db.execute(text(
                "SELECT c.*, r.id AS record_id, r.trace_id, r.model, r.protocol_type, r.stream, "
                "r.request_payload, r.response_payload, r.completed_at "
                "FROM conversation_candidates c JOIN conversation_records r ON r.id=c.conversation_record_id "
                "WHERE c.status=:status ORDER BY c.created_at ASC"
            ), {"status": status}).mappings().all()
        return [self._candidate_detail(row) for row in rows]

    def get_candidate(self, candidate_id):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM conversation_candidates WHERE id=:id"), {"id": candidate_id}).mappings().first()
        return self._candidate(row) if row else None

    def get_candidate_detail(self, candidate_id):
        with get_db() as db:
            row = db.execute(text(
                "SELECT c.*, r.id AS record_id, r.trace_id, r.model, r.protocol_type, r.stream, "
                "r.request_payload, r.response_payload, r.completed_at "
                "FROM conversation_candidates c JOIN conversation_records r ON r.id=c.conversation_record_id "
                "WHERE c.id=:id"
            ), {"id": candidate_id}).mappings().first()
        return self._candidate_detail(row) if row else None

    def review_candidate(self, candidate_id, status, note, reviewed_at):
        with get_db() as db:
            result = db.execute(text(
                "UPDATE conversation_candidates SET status=:status, review_note=:note, reviewed_at=:reviewed_at "
                "WHERE id=:id AND status='pending_review'"
            ), {"id": candidate_id, "status": status, "note": note, "reviewed_at": reviewed_at})
        return result.rowcount == 1

    def get_draft_by_candidate_id(self, candidate_id):
        return self._draft_one(
            "candidate_id=:candidate_id ORDER BY revision DESC", {"candidate_id": candidate_id},
        )

    def next_draft_revision(self, candidate_id):
        with get_db() as db:
            row = db.execute(text(
                "SELECT COALESCE(MAX(revision),0)+1 AS next_revision FROM knowledge_drafts WHERE candidate_id=:candidate_id"
            ), {"candidate_id": candidate_id}).mappings().first()
        return int(row["next_revision"])

    def get_draft(self, draft_id):
        return self._draft_one("id=:id", {"id": draft_id})

    def save_draft(self, draft):
        with get_db() as db:
            db.execute(text(
                "INSERT INTO knowledge_drafts (id,candidate_id,revision,title,summary,content,tags,generation_mode,status,graph_suggestion,created_at,updated_at) "
                "VALUES (:id,:candidate_id,:revision,:title,:summary,:content,:tags,:generation_mode,:status,:graph_suggestion,:created_at,:updated_at)"
            ), self._draft_params(draft))
        return draft

    def update_draft(self, draft):
        with get_db() as db:
            db.execute(text(
                "UPDATE knowledge_drafts SET title=:title,summary=:summary,content=:content,tags=:tags,"
                "generation_mode=:generation_mode,status=:status,graph_suggestion=:graph_suggestion,updated_at=:updated_at WHERE id=:id"
            ), self._draft_params(draft))
        return draft

    def get_or_create_card(self, candidate_id, now):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_cards WHERE candidate_id=:candidate_id"), {"candidate_id": candidate_id}).mappings().first()
            if row:
                return self._card(row)
            from app.domain.entities import KnowledgeCardEntity
            card = KnowledgeCardEntity(id=uuid.uuid4().hex, candidate_id=candidate_id, status="draft", current_version=0, created_at=now, updated_at=now)
            try:
                db.execute(text(
                    "INSERT INTO knowledge_cards (id,candidate_id,status,current_version,created_at,updated_at) VALUES (:id,:candidate_id,:status,:current_version,:created_at,:updated_at)"
                ), vars(card))
                return card
            except IntegrityError:
                pass
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_cards WHERE candidate_id=:candidate_id"), {"candidate_id": candidate_id}).mappings().first()
        if row:
            return self._card(row)
        raise RuntimeError("Unable to create or load knowledge card")

    def next_card_version(self, card_id):
        with get_db() as db:
            row = db.execute(text("SELECT COALESCE(MAX(version),0)+1 AS next_version FROM knowledge_card_versions WHERE card_id=:card_id"), {"card_id": card_id}).mappings().first()
        return int(row["next_version"])

    def save_card_version(self, version):
        try:
            with get_db() as db:
                db.execute(text(
                    "INSERT INTO knowledge_card_versions (id,card_id,version,kb_id,title,summary,content,tags,source_draft_id,published_at) "
                    "VALUES (:id,:card_id,:version,:kb_id,:title,:summary,:content,:tags,:source_draft_id,:published_at)"
                ), self._version_params(version))
            return version
        except IntegrityError:
            existing = self.get_card_version_by_source_draft_id(version.source_draft_id)
            if existing:
                return existing
            raise

    def get_card_version(self, version_id):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_card_versions WHERE id=:id"), {"id": version_id}).mappings().first()
        return self._version(row) if row else None

    def get_card_version_by_source_draft_id(self, draft_id):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_card_versions WHERE source_draft_id=:draft_id"), {"draft_id": draft_id}).mappings().first()
        return self._version(row) if row else None

    def update_card_published(self, card_id, version, now):
        with get_db() as db:
            db.execute(text(
                "UPDATE knowledge_cards SET status='published', "
                "current_version=CASE WHEN current_version < :version THEN :version ELSE current_version END, "
                "updated_at=:updated_at WHERE id=:id"
            ), {"id": card_id, "version": version, "updated_at": now})
            row = db.execute(text("SELECT * FROM knowledge_cards WHERE id=:id"), {"id": card_id}).mappings().first()
        if not row:
            raise ValueError("Knowledge card not found")
        return self._card(row)

    def list_cards(self, kb_id=None):
        condition = "" if not kb_id else "WHERE v.kb_id=:kb_id"
        params = {} if not kb_id else {"kb_id": kb_id}
        with get_db() as db:
            rows = db.execute(text(
                "SELECT c.*,v.id AS version_id,v.kb_id,v.title,v.summary,v.content,v.tags,v.source_draft_id,v.published_at "
                "FROM knowledge_cards c JOIN knowledge_card_versions v ON v.card_id=c.id AND v.version=c.current_version " + condition + " ORDER BY v.published_at DESC"
            ), params).mappings().all()
        return [{"card": self._card(row), "version": self._version_from_join(row)} for row in rows]

    def get_projection(self, card_version_id, projection_type):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_card_projections WHERE card_version_id=:card_version_id AND projection_type=:projection_type"), {"card_version_id": card_version_id, "projection_type": projection_type}).mappings().first()
        return self._projection(row) if row else None

    def save_projection(self, projection):
        try:
            with get_db() as db:
                db.execute(text("INSERT INTO knowledge_card_projections (id,card_version_id,projection_type,external_id,created_at) VALUES (:id,:card_version_id,:projection_type,:external_id,:created_at)"), vars(projection))
            return projection
        except IntegrityError:
            existing = self.get_projection(projection.card_version_id, projection.projection_type)
            if existing:
                return existing
            raise

    def get_wiki_by_card_version_id(self, version_id):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_wiki_pages WHERE card_version_id=:id"), {"id": version_id}).mappings().first()
        return self._wiki(row) if row else None

    def save_wiki_page(self, page):
        try:
            with get_db() as db:
                db.execute(text("INSERT INTO knowledge_wiki_pages (id,kb_id,card_version_id,title,slug,content,created_at,updated_at) VALUES (:id,:kb_id,:card_version_id,:title,:slug,:content,:created_at,:updated_at)"), vars(page))
            return page
        except IntegrityError:
            existing = self.get_wiki_by_card_version_id(page.card_version_id)
            if existing:
                return existing
            raise

    def list_wiki_pages(self, kb_id):
        with get_db() as db:
            rows = db.execute(text("SELECT * FROM knowledge_wiki_pages WHERE kb_id=:kb_id ORDER BY title"), {"kb_id": kb_id}).mappings().all()
        return [self._wiki(row) for row in rows]

    def get_graph_node(self, kb_id, normalized_name):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_graph_nodes WHERE kb_id=:kb_id AND normalized_name=:normalized_name"), {"kb_id": kb_id, "normalized_name": normalized_name}).mappings().first()
        return self._node(row) if row else None

    def upsert_graph_node(self, node):
        try:
            with get_db() as db:
                db.execute(text("INSERT INTO knowledge_graph_nodes (id,kb_id,name,normalized_name,entity_type,created_at) VALUES (:id,:kb_id,:name,:normalized_name,:entity_type,:created_at)"), vars(node))
            return node
        except IntegrityError:
            existing = self.get_graph_node(node.kb_id, node.normalized_name)
            if existing:
                return existing
            raise

    def save_graph_edge_if_absent(self, edge):
        try:
            with get_db() as db:
                db.execute(text("INSERT INTO knowledge_graph_edges (id,kb_id,source_node_id,target_node_id,relation_type,source_card_version_id,evidence,confidence,created_at) VALUES (:id,:kb_id,:source_node_id,:target_node_id,:relation_type,:source_card_version_id,:evidence,:confidence,:created_at)"), vars(edge))
            return edge
        except IntegrityError:
            with get_db() as db:
                row = db.execute(text("SELECT * FROM knowledge_graph_edges WHERE source_card_version_id=:version_id AND source_node_id=:source_id AND target_node_id=:target_id AND relation_type=:relation_type"), {"version_id": edge.source_card_version_id, "source_id": edge.source_node_id, "target_id": edge.target_node_id, "relation_type": edge.relation_type}).mappings().first()
            if row:
                return self._edge(row)
            raise

    def list_graph(self, kb_id, entity_query=None):
        params = {"kb_id": kb_id}
        condition = ""
        if entity_query:
            params["query"] = f"%{entity_query.lower()}%"
            condition = " AND (sn.normalized_name LIKE :query OR tn.normalized_name LIKE :query)"
        with get_db() as db:
            rows = db.execute(text(
                "SELECT e.*, sn.name AS source_name, tn.name AS target_name FROM knowledge_graph_edges e "
                "JOIN knowledge_graph_nodes sn ON sn.id=e.source_node_id JOIN knowledge_graph_nodes tn ON tn.id=e.target_node_id "
                "WHERE e.kb_id=:kb_id" + condition + " ORDER BY e.created_at DESC LIMIT 100"
            ), params).mappings().all()
        return [dict(row) for row in rows]

    def graph_document_ids(self, kb_id, query, limit=3):
        terms = [term.lower() for term in query.split() if len(term.strip()) > 1][:8]
        if not terms:
            return []
        with get_db() as db:
            nodes = db.execute(text("SELECT id FROM knowledge_graph_nodes WHERE kb_id=:kb_id AND (" + " OR ".join(f"normalized_name LIKE :term_{index}" for index, _ in enumerate(terms)) + ") LIMIT 10"), {"kb_id": kb_id, **{f"term_{index}": f"%{term}%" for index, term in enumerate(terms)}}).mappings().all()
            node_ids = [row["id"] for row in nodes]
            if not node_ids:
                return []
            binds = {f"node_{index}": node_id for index, node_id in enumerate(node_ids)}
            placeholders = ",".join(f":node_{index}" for index in range(len(node_ids)))
            rows = db.execute(text(
                "SELECT DISTINCT p.external_id FROM knowledge_graph_edges e "
                "JOIN knowledge_card_projections p ON p.card_version_id=e.source_card_version_id AND p.projection_type='kb_document' "
                f"WHERE e.kb_id=:kb_id AND (e.source_node_id IN ({placeholders}) OR e.target_node_id IN ({placeholders})) "
                "AND p.external_id IS NOT NULL LIMIT :limit"
            ), {"kb_id": kb_id, "limit": limit, **binds}).mappings().all()
        return [row["external_id"] for row in rows]

    def _draft_one(self, clause, params):
        with get_db() as db:
            row = db.execute(text("SELECT * FROM knowledge_drafts WHERE " + clause), params).mappings().first()
        return self._draft(row) if row else None

    @staticmethod
    def _json(value, default):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return default
        return value if value is not None else default

    def _candidate_detail(self, row):
        return {"candidate": self._candidate(row), "record": ConversationRecordEntity(id=row["record_id"], request_log_id="", trace_id=row["trace_id"], origin="external", model=row["model"], protocol_type=row["protocol_type"], stream=bool(row["stream"]), request_payload=row["request_payload"], response_payload=row["response_payload"], completed_at=row["completed_at"])}

    @staticmethod
    def _candidate(row):
        return ConversationCandidateEntity(id=row["id"], conversation_record_id=row["conversation_record_id"], status=row["status"], eligibility_policy_version=row["eligibility_policy_version"], created_at=row["created_at"], updated_at=row["updated_at"], reviewed_at=row.get("reviewed_at"), review_note=row.get("review_note"))

    def _draft(self, row):
        return KnowledgeDraftEntity(id=row["id"], candidate_id=row["candidate_id"], revision=int(row["revision"]), title=row["title"], summary=row["summary"], content=row["content"], tags=self._json(row["tags"], []), generation_mode=row["generation_mode"], status=row["status"], graph_suggestion=self._json(row["graph_suggestion"], None), created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _card(row):
        return KnowledgeCardEntity(id=row["id"], candidate_id=row["candidate_id"], status=row["status"], current_version=int(row["current_version"]), created_at=row["created_at"], updated_at=row["updated_at"])

    def _version(self, row):
        return KnowledgeCardVersionEntity(id=row["id"], card_id=row["card_id"], version=int(row["version"]), kb_id=row["kb_id"], title=row["title"], summary=row["summary"], content=row["content"], tags=self._json(row["tags"], []), source_draft_id=row["source_draft_id"], published_at=row["published_at"])

    def _version_from_join(self, row):
        return KnowledgeCardVersionEntity(id=row["version_id"], card_id=row["id"], version=int(row["current_version"]), kb_id=row["kb_id"], title=row["title"], summary=row["summary"], content=row["content"], tags=self._json(row["tags"], []), source_draft_id=row["source_draft_id"], published_at=row["published_at"])

    @staticmethod
    def _projection(row):
        return KnowledgeProjectionEntity(id=row["id"], card_version_id=row["card_version_id"], projection_type=row["projection_type"], external_id=row["external_id"], created_at=row["created_at"])

    @staticmethod
    def _wiki(row):
        return KnowledgeWikiPageEntity(id=row["id"], kb_id=row["kb_id"], card_version_id=row["card_version_id"], title=row["title"], slug=row["slug"], content=row["content"], created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _node(row):
        return KnowledgeGraphNodeEntity(id=row["id"], kb_id=row["kb_id"], name=row["name"], normalized_name=row["normalized_name"], entity_type=row["entity_type"], created_at=row["created_at"])

    @staticmethod
    def _edge(row):
        return KnowledgeGraphEdgeEntity(id=row["id"], kb_id=row["kb_id"], source_node_id=row["source_node_id"], target_node_id=row["target_node_id"], relation_type=row["relation_type"], source_card_version_id=row["source_card_version_id"], evidence=row["evidence"], confidence=float(row["confidence"]), created_at=row["created_at"])

    def _draft_params(self, draft):
        return {"id": draft.id, "candidate_id": draft.candidate_id, "revision": draft.revision, "title": draft.title, "summary": draft.summary, "content": draft.content, "tags": json.dumps(draft.tags, ensure_ascii=False), "generation_mode": draft.generation_mode, "status": draft.status, "graph_suggestion": json.dumps(draft.graph_suggestion, ensure_ascii=False) if draft.graph_suggestion else None, "created_at": draft.created_at, "updated_at": draft.updated_at}

    def _version_params(self, version):
        return {"id": version.id, "card_id": version.card_id, "version": version.version, "kb_id": version.kb_id, "title": version.title, "summary": version.summary, "content": version.content, "tags": json.dumps(version.tags, ensure_ascii=False), "source_draft_id": version.source_draft_id, "published_at": version.published_at}
