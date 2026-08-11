from app.application.services.kb_service import KbService
from app.domain.entities import KbDocumentEntity
from app.types.models import UploadDocDTO


class FakeDocumentRepository:
    def __init__(self, initial=None, claim_result=True):
        self.docs = {} if initial is None else {initial.id: initial}
        self.claim_result = claim_result
        self.deleted = []
        self.saved_tasks = []

    def find_doc_by_id(self, doc_id):
        return self.docs.get(doc_id)

    def save_doc_if_absent(self, document):
        if not self.claim_result:
            self.docs[document.id] = KbDocumentEntity(
                id=document.id, kb_id=document.kb_id, name=document.name,
                source_type=document.source_type, source_path=document.source_path,
                status="ready", created_at=document.created_at, updated_at=document.updated_at,
            )
            return False
        self.docs[document.id] = document
        return True

    def delete_doc_by_id(self, doc_id):
        self.deleted.append(doc_id)
        self.docs.pop(doc_id, None)

    def save_task(self, task):
        self.saved_tasks.append(task)


class SynchronousProjectionService(KbService):
    def _run_import_pipeline(self, _kb_id, doc_id, _task_id, _dto):
        self.repo.docs[doc_id].status = "ready"


def dto():
    return UploadDocDTO(
        filename="knowledge-card.md", content="# Knowledge", file_type="md", source_type="knowledge_card",
    )


def test_concurrent_projection_claim_waits_for_existing_ready_document_without_deleting_it():
    repo = FakeDocumentRepository(claim_result=False)
    service = SynchronousProjectionService(repo, None, None, None)

    document = service.import_doc_sync("kb-1", dto(), "knowledge-card-version-1")

    assert document.id == "knowledge-card-version-1"
    assert repo.deleted == []
    assert repo.saved_tasks == []


def test_failed_projection_is_replaced_only_after_it_has_finished():
    failed = KbDocumentEntity(
        id="knowledge-card-version-1", kb_id="kb-1", name="old", source_type="knowledge_card",
        source_path="old", status="error", error_message="embedding failed",
    )
    repo = FakeDocumentRepository(initial=failed)
    service = SynchronousProjectionService(repo, None, None, None)

    document = service.import_doc_sync("kb-1", dto(), failed.id)

    assert document.status == "ready"
    assert repo.deleted == [failed.id]
    assert len(repo.saved_tasks) == 1
