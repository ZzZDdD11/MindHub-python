from app.domain.entities import KbChunkEntity
from app.domain.knowledge import RagService


class FakeRetriever:
    def hybrid_search(self, kb_id, query, embedding, top_k, *_):
        from app.domain.entities import SearchResultEntity
        return [SearchResultEntity(chunk_id="base", doc_id="base-doc", content="base", score=0.9, metadata={})]


class FakeEmbedder:
    def embed(self, query, model):
        return [0.1]


class FakeGraphRepository:
    def graph_document_ids(self, kb_id, query, limit=3):
        assert kb_id == "kb-a"
        assert limit == 3
        return ["graph-doc", "base-doc"]


class FakeKbRepository:
    def find_chunk_by_doc_id(self, document_id):
        if document_id == "graph-doc":
            return [KbChunkEntity(id="graph", doc_id="graph-doc", kb_id="kb-a", content="graph evidence", chunk_index=0)]
        return []


def test_graph_hybrid_adds_only_one_hop_documents_and_preserves_top_k():
    rag = RagService(
        FakeRetriever(), FakeEmbedder(), None, None,
        graph_repository=FakeGraphRepository(), kb_repository=FakeKbRepository(),
    )

    results = rag.search_by_mode("kb-a", "request id", 2, "graph_hybrid", "embedding-model")

    assert [result.chunk_id for result in results] == ["base", "graph"]
    assert results[1].metadata["graphExpanded"] is True


def test_graph_hybrid_never_adds_more_than_three_graph_chunks():
    class ManyChunks:
        def find_chunk_by_doc_id(self, document_id):
            return [
                KbChunkEntity(id=f"{document_id}-{index}", doc_id=document_id, kb_id="kb-a", content="evidence", chunk_index=index)
                for index in range(4)
            ]

    rag = RagService(
        FakeRetriever(), FakeEmbedder(), None, None,
        graph_repository=FakeGraphRepository(), kb_repository=ManyChunks(),
    )

    results = rag.search_by_mode("kb-a", "request id", 10, "graph_hybrid", "embedding-model")

    assert len(results) == 4
    assert sum(item.metadata.get("graphExpanded", False) for item in results) == 3


def test_graph_hybrid_falls_back_to_hybrid_when_graph_lookup_fails():
    class BrokenGraph:
        def graph_document_ids(self, *_):
            raise RuntimeError("graph unavailable")

    rag = RagService(
        FakeRetriever(), FakeEmbedder(), None, None,
        graph_repository=BrokenGraph(), kb_repository=FakeKbRepository(),
    )

    results = rag.search_by_mode("kb-a", "request id", 2, "graph_hybrid", "embedding-model")

    assert [result.chunk_id for result in results] == ["base"]
