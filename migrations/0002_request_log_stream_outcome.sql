ALTER TABLE request_logs
    ADD COLUMN stream_outcome VARCHAR(16) DEFAULT NULL COMMENT '流式终态(completed/failed/canceled/blocked)';

CREATE INDEX idx_request_logs_stream_outcome ON request_logs (stream_outcome);
