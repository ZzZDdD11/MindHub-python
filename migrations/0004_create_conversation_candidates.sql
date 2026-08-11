CREATE TABLE conversation_candidates (
    id VARCHAR(64) NOT NULL,
    conversation_record_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
    eligibility_policy_version VARCHAR(64) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conversation_candidates_record_id (conversation_record_id),
    KEY idx_conversation_candidates_status_created_at (status, created_at),
    CONSTRAINT fk_conversation_candidates_record
        FOREIGN KEY (conversation_record_id) REFERENCES conversation_records(id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='待审核完整对话候选';
