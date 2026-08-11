"""Administrator-governed knowledge lifecycle services."""
from datetime import datetime, timezone
import json
import re
import uuid

from app.domain.entities import (
    KnowledgeCardVersionEntity, KnowledgeDraftEntity, KnowledgeGraphEdgeEntity,
    KnowledgeGraphNodeEntity, KnowledgeProjectionEntity, KnowledgeWikiPageEntity,
)


class KnowledgeLifecycleService:
    """Moves approved conversation candidates through draft, publication and projections."""

    def __init__(self, repository, kb_service=None, gateway_service=None, pipeline_model=None):
        self.repo = repository
        self.kb_service = kb_service
        self.gateway = gateway_service
        self.pipeline_model = pipeline_model

    def list_candidates(self, status="pending_review"):
        return self.repo.list_candidate_details(status)

    def get_candidate_detail(self, candidate_id):
        detail = self.repo.get_candidate_detail(candidate_id)
        if not detail:
            raise ValueError("Candidate not found")
        return detail

    def approve_candidate(self, candidate_id, note=None):
        return self._review_candidate(candidate_id, "approved", note)

    def reject_candidate(self, candidate_id, note=None):
        return self._review_candidate(candidate_id, "rejected", note)

    def _review_candidate(self, candidate_id, status, note):
        candidate = self.repo.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Candidate not found")
        if candidate.status != "pending_review":
            raise ValueError("Candidate must be pending_review")
        reviewed_at = self._now()
        if not self.repo.review_candidate(candidate_id, status, self._clean_note(note), reviewed_at):
            raise ValueError("Candidate must be pending_review")
        candidate.status = status
        candidate.review_note = self._clean_note(note)
        candidate.reviewed_at = reviewed_at
        return candidate

    def create_manual_draft(self, candidate_id, title, summary, content, tags):
        self._require_approved_candidate(candidate_id)
        existing = self.repo.get_draft_by_candidate_id(candidate_id)
        is_revision = bool(existing and existing.status == "published")
        now = self._now()
        draft = KnowledgeDraftEntity(
            id=uuid.uuid4().hex if is_revision or not existing else existing.id,
            candidate_id=candidate_id,
            revision=(self.repo.next_draft_revision(candidate_id) if is_revision or not existing else existing.revision),
            title=self._required_text(title, "title"),
            summary=self._required_text(summary, "summary"),
            content=self._required_text(content, "content"),
            tags=self._clean_tags(tags),
            generation_mode="manual",
            status="draft",
            graph_suggestion=None,
            created_at=now if is_revision or not existing else existing.created_at,
            updated_at=now,
        )
        return self.repo.update_draft(draft) if existing and not is_revision else self.repo.save_draft(draft)

    def update_draft(self, draft_id, title, summary, content, tags):
        draft = self.repo.get_draft(draft_id)
        if not draft:
            raise ValueError("Draft not found")
        self._require_approved_candidate(draft.candidate_id)
        if draft.status == "published":
            raise ValueError("Published draft cannot be edited")
        draft.title = self._required_text(title, "title")
        draft.summary = self._required_text(summary, "summary")
        draft.content = self._required_text(content, "content")
        draft.tags = self._clean_tags(tags)
        draft.updated_at = self._now()
        return self.repo.update_draft(draft)

    def publish_draft(self, draft_id, kb_id):
        draft = self.repo.get_draft(draft_id)
        if not draft:
            raise ValueError("Draft not found")
        self._require_approved_candidate(draft.candidate_id)
        if not kb_id:
            raise ValueError("kb_id is required")
        if self.kb_service and not self.kb_service.get_kb(kb_id):
            raise ValueError("Knowledge base not found")
        now = self._now()
        card = self.repo.get_or_create_card(draft.candidate_id, now)
        existing_version = getattr(self.repo, "get_card_version_by_source_draft_id", lambda _: None)(draft.id)
        if existing_version:
            if existing_version.kb_id != kb_id:
                raise ValueError("Draft publication target cannot be changed after version creation")
            version = existing_version
            version_number = version.version
        else:
            version_number = self.repo.next_card_version(card.id)
            version = KnowledgeCardVersionEntity(
                id=uuid.uuid4().hex,
                card_id=card.id,
                version=version_number,
                kb_id=kb_id,
                title=draft.title,
                summary=draft.summary,
                content=draft.content,
                tags=list(draft.tags or []),
                source_draft_id=draft.id,
                published_at=now,
            )
            version = self.repo.save_card_version(version)
        wiki = self._project_to_wiki(version)
        graph = self.generate_graph_for_version(version.id) if self.pipeline_model else {"nodes": [], "edges": []}
        projection = self._project_to_kb(version)
        card = self.repo.update_card_published(card.id, version_number, now)
        draft.status = "published"
        draft.updated_at = now
        self.repo.update_draft(draft)
        return {"card": card, "version": version, "projection": projection, "wiki": wiki, "graph": graph}

    def generate_ai_draft(self, candidate_id):
        detail = self.get_candidate_detail(candidate_id)
        self._require_approved_candidate(candidate_id)
        record = detail["record"]
        suggestion = self._call_pipeline_json(
            "Create a concise knowledge draft from the approved conversation. Return JSON only with "
            "title, summary, content, tags, entities, relations. Relations must include source, target, type, evidence, confidence.",
            f"Request:\n{record.request_payload}\n\nResponse:\n{record.response_payload}",
        )
        draft = self.create_manual_draft(
            candidate_id, suggestion.get("title"), suggestion.get("summary"), suggestion.get("content"), suggestion.get("tags", []),
        )
        draft.generation_mode = "ai"
        draft.graph_suggestion = {"entities": suggestion.get("entities", []), "relations": suggestion.get("relations", [])}
        return self.repo.update_draft(draft)

    def generate_graph_for_version(self, card_version_id):
        version = self.repo.get_card_version(card_version_id)
        if not version:
            raise ValueError("Card version not found")
        suggestion = self._call_pipeline_json(
            "Extract a small knowledge graph from this published knowledge card. Return JSON only with "
            "entities [{name,type}] and relations [{source,target,type,evidence,confidence}].",
            self._wiki_markdown(version),
        )
        return self.project_graph(version.id, suggestion)

    def project_graph(self, card_version_id, suggestion):
        version = self.repo.get_card_version(card_version_id)
        if not version:
            raise ValueError("Card version not found")
        if not isinstance(suggestion, dict):
            raise ValueError("Graph suggestion must be an object")
        entities = suggestion.get("entities", [])
        relations = suggestion.get("relations", [])
        if not isinstance(entities, list) or not isinstance(relations, list):
            raise ValueError("Graph suggestion entities and relations must be lists")
        if any(not isinstance(item, dict) or not str(item.get("name") or "").strip() for item in entities):
            raise ValueError("Graph suggestion contains invalid entities")
        if any(
            not isinstance(relation, dict)
            or not str(relation.get("source") or "").strip()
            or not str(relation.get("target") or "").strip()
            for relation in relations
        ):
            raise ValueError("Graph suggestion contains invalid relations")
        nodes = {}
        for item in entities:
            node = self._node_for(version.kb_id, item)
            if node:
                nodes[node.normalized_name] = node
        edges = []
        for relation in relations[:20]:
            source = self._node_for(version.kb_id, {"name": relation.get("source"), "type": "concept"})
            target = self._node_for(version.kb_id, {"name": relation.get("target"), "type": "concept"})
            if not source or not target or source.id == target.id:
                continue
            confidence = relation.get("confidence", 0.5)
            try:
                confidence = min(1.0, max(0.0, float(confidence)))
            except (TypeError, ValueError):
                confidence = 0.5
            edge = KnowledgeGraphEdgeEntity(
                id=uuid.uuid4().hex,
                kb_id=version.kb_id,
                source_node_id=source.id,
                target_node_id=target.id,
                relation_type=self._safe_relation(relation.get("type")),
                source_card_version_id=version.id,
                evidence=self._required_text(relation.get("evidence") or version.summary, "evidence")[:1000],
                confidence=confidence,
                created_at=self._now(),
            )
            edges.append(self.repo.save_graph_edge_if_absent(edge))
            nodes[source.normalized_name] = source
            nodes[target.normalized_name] = target
        return {"nodes": list(nodes.values()), "edges": edges}

    def _project_to_kb(self, version):
        existing = self.repo.get_projection(version.id, "kb_document")
        if existing:
            return existing
        document_id = None
        if self.kb_service:
            from app.types.models import UploadDocDTO
            document_id = f"knowledge-card-{version.id}"
            doc = self.kb_service.import_doc_sync(version.kb_id, UploadDocDTO(
                filename=f"knowledge-card-{version.id}.md",
                content=self._wiki_markdown(version),
                file_type="md",
                source_type="knowledge_card",
            ), document_id)
            document_id = doc.id
        projection = KnowledgeProjectionEntity(
            id=uuid.uuid4().hex,
            card_version_id=version.id,
            projection_type="kb_document",
            external_id=document_id,
            created_at=self._now(),
        )
        return self.repo.save_projection(projection)

    def _project_to_wiki(self, version):
        existing = self.repo.get_wiki_by_card_version_id(version.id)
        if existing:
            return existing
        slug = self._slugify(version.title, version.id)
        page = KnowledgeWikiPageEntity(
            id=uuid.uuid4().hex,
            kb_id=version.kb_id,
            card_version_id=version.id,
            title=version.title,
            slug=slug,
            content=self._wiki_markdown(version),
            created_at=self._now(),
            updated_at=self._now(),
        )
        return self.repo.save_wiki_page(page)

    def _node_for(self, kb_id, item):
        if not isinstance(item, dict):
            return None
        name = self._required_text(item.get("name"), "entity name")[:255]
        normalized = self._normalize_entity(name)
        if not normalized:
            return None
        existing = self.repo.get_graph_node(kb_id, normalized)
        if existing:
            return existing
        return self.repo.upsert_graph_node(KnowledgeGraphNodeEntity(
            id=uuid.uuid4().hex,
            kb_id=kb_id,
            name=name,
            normalized_name=normalized,
            entity_type=self._safe_relation(item.get("type") or "concept"),
            created_at=self._now(),
        ))

    def _require_approved_candidate(self, candidate_id):
        candidate = self.repo.get_candidate(candidate_id)
        if not candidate:
            raise ValueError("Candidate not found")
        if candidate.status != "approved":
            raise ValueError("Candidate must be approved")
        return candidate

    def _call_pipeline_json(self, instruction, source):
        if not self.pipeline_model or not self.gateway:
            raise ValueError("KNOWLEDGE_PIPELINE_MODEL is not configured")
        from app.domain.entities import ProxyRequestEntity
        response = self.gateway.forward(ProxyRequestEntity(
            model=self.pipeline_model,
            body={
                "model": self.pipeline_model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": source[:100000]},
                ],
            },
        ))
        if not response.success:
            raise ValueError("Knowledge pipeline request failed")
        try:
            payload = json.loads(response.body)
            content = payload["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            suggestion = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("Knowledge pipeline returned invalid JSON")
        if not isinstance(suggestion, dict):
            raise ValueError("Knowledge pipeline returned invalid JSON")
        return suggestion

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clean_note(value):
        return str(value or "").strip()[:2000] or None

    @staticmethod
    def _required_text(value, field_name):
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} is required")
        return text

    @staticmethod
    def _clean_tags(tags):
        if not isinstance(tags, list):
            return []
        return list(dict.fromkeys(str(tag).strip()[:64] for tag in tags if str(tag).strip()))[:20]

    @staticmethod
    def _normalize_entity(name):
        return re.sub(r"\s+", " ", name.strip().lower())[:255]

    @staticmethod
    def _safe_relation(value):
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(value or "related_to").strip().lower())
        return cleaned[:64] or "related_to"

    @staticmethod
    def _slugify(title, fallback):
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        prefix = slug[:120] or "knowledge"
        return f"{prefix}-{fallback[:12]}"

    @staticmethod
    def _wiki_markdown(version):
        tags = ", ".join(version.tags or [])
        return f"# {version.title}\n\n> {version.summary}\n\n{version.content}\n\n---\n\n标签：{tags}\n"
