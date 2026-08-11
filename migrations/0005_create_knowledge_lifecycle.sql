ALTER TABLE conversation_candidates
    ADD COLUMN reviewed_at VARCHAR(40) DEFAULT NULL,
    ADD COLUMN review_note TEXT DEFAULT NULL;

CREATE TABLE knowledge_drafts (
    id VARCHAR(64) NOT NULL,
    candidate_id VARCHAR(64) NOT NULL,
    revision INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    content MEDIUMTEXT NOT NULL,
    tags JSON DEFAULT NULL,
    generation_mode VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    graph_suggestion JSON DEFAULT NULL,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_drafts_candidate_revision (candidate_id, revision),
    CONSTRAINT fk_knowledge_drafts_candidate FOREIGN KEY (candidate_id)
        REFERENCES conversation_candidates(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人工审核后的知识草稿';

CREATE TABLE knowledge_cards (
    id VARCHAR(64) NOT NULL,
    candidate_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    current_version INT NOT NULL DEFAULT 0,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_cards_candidate_id (candidate_id),
    CONSTRAINT fk_knowledge_cards_candidate FOREIGN KEY (candidate_id)
        REFERENCES conversation_candidates(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识卡';

CREATE TABLE knowledge_card_versions (
    id VARCHAR(64) NOT NULL,
    card_id VARCHAR(64) NOT NULL,
    version INT NOT NULL,
    kb_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    content MEDIUMTEXT NOT NULL,
    tags JSON DEFAULT NULL,
    source_draft_id VARCHAR(64) NOT NULL,
    published_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_card_versions_card_version (card_id, version),
    UNIQUE KEY uk_knowledge_card_versions_source_draft_id (source_draft_id),
    KEY idx_knowledge_card_versions_kb_id (kb_id),
    CONSTRAINT fk_knowledge_card_versions_card FOREIGN KEY (card_id)
        REFERENCES knowledge_cards(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_card_versions_kb FOREIGN KEY (kb_id)
        REFERENCES kb_knowledge_bases(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_card_versions_draft FOREIGN KEY (source_draft_id)
        REFERENCES knowledge_drafts(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='不可变知识卡版本';

CREATE TABLE knowledge_card_projections (
    id VARCHAR(64) NOT NULL,
    card_version_id VARCHAR(64) NOT NULL,
    projection_type VARCHAR(32) NOT NULL,
    external_id VARCHAR(64) DEFAULT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_card_projections_version_type (card_version_id, projection_type),
    CONSTRAINT fk_knowledge_card_projections_version FOREIGN KEY (card_version_id)
        REFERENCES knowledge_card_versions(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识卡可重建投影';

CREATE TABLE knowledge_wiki_pages (
    id VARCHAR(64) NOT NULL,
    kb_id VARCHAR(64) NOT NULL,
    card_version_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(160) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_wiki_pages_card_version_id (card_version_id),
    UNIQUE KEY uk_knowledge_wiki_pages_kb_slug (kb_id, slug),
    CONSTRAINT fk_knowledge_wiki_pages_kb FOREIGN KEY (kb_id)
        REFERENCES kb_knowledge_bases(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_wiki_pages_version FOREIGN KEY (card_version_id)
        REFERENCES knowledge_card_versions(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识卡 Wiki 投影';

CREATE TABLE knowledge_graph_nodes (
    id VARCHAR(64) NOT NULL,
    kb_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_graph_nodes_kb_name (kb_id, normalized_name),
    CONSTRAINT fk_knowledge_graph_nodes_kb FOREIGN KEY (kb_id)
        REFERENCES kb_knowledge_bases(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识图谱节点';

CREATE TABLE knowledge_graph_edges (
    id VARCHAR(64) NOT NULL,
    kb_id VARCHAR(64) NOT NULL,
    source_node_id VARCHAR(64) NOT NULL,
    target_node_id VARCHAR(64) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    source_card_version_id VARCHAR(64) NOT NULL,
    evidence TEXT NOT NULL,
    confidence DECIMAL(4,3) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_graph_edges_version_relation (source_card_version_id, source_node_id, target_node_id, relation_type),
    KEY idx_knowledge_graph_edges_kb_source (kb_id, source_node_id),
    CONSTRAINT fk_knowledge_graph_edges_kb FOREIGN KEY (kb_id)
        REFERENCES kb_knowledge_bases(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_graph_edges_source FOREIGN KEY (source_node_id)
        REFERENCES knowledge_graph_nodes(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_graph_edges_target FOREIGN KEY (target_node_id)
        REFERENCES knowledge_graph_nodes(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_knowledge_graph_edges_version FOREIGN KEY (source_card_version_id)
        REFERENCES knowledge_card_versions(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='带来源证据的知识图谱关系';
