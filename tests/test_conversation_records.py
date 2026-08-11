import asyncio
from types import SimpleNamespace

from app.application.services.misc_services import ProxyService
from app.domain.entities import ProxyCallContext, ProxyResponseEntity


class FakeLogRepository:
    def __init__(self):
        self.entries = []

    def insert_log(self, entry):
        self.entries.append(entry)


class FakeConversationRecordRepository:
    def __init__(self):
        self.records = []
        self.candidates = []

    def create_if_absent(self, record):
        self.records.append(record)
        return record


class FakeConversationCandidateService:
    def __init__(self, records, error=None):
        self.records = records
        self.error = error

    def enqueue_record(self, record):
        if self.error:
            raise self.error
        self.records.append(record)


class FakeSecurityScanner:
    def scan(self, *_):
        return SimpleNamespace(
            risk_level="High", risk_score=100, summary="blocked", blocked=True,
            blocked_reason="policy", sanitized=False,
        )


class FakeGateway:
    def __init__(self, response=None, events=None):
        self.response = response
        self.events = events or []

    def forward(self, request):
        return self.response

    async def forward_stream_async(self, request):
        request.dispatched_channel_id = "channel-123"
        request.dispatched_channel_name = "primary"
        request.upstream_model = "gpt-4o-upstream"
        for event in self.events:
            yield event


def service_for(gateway, *, log_error=None, record_error=None, candidate_error=None, security_enabled=False):
    logs = FakeLogRepository()
    if log_error:
        def insert_log(_):
            raise log_error
        logs.insert_log = insert_log
    records = FakeConversationRecordRepository()
    if record_error:
        def create_if_absent(_):
            raise record_error
        records.create_if_absent = create_if_absent
    candidate_service = FakeConversationCandidateService(records.candidates, candidate_error)
    service = ProxyService(
        gateway,
        FakeSecurityScanner() if security_enabled else None,
        SimpleNamespace(enabled=security_enabled),
        logs,
        conversation_record_repository=records,
        conversation_candidate_service=candidate_service,
    )
    context = ProxyCallContext(request_id="request-123", api_key_id="key-123")
    return service, logs, records, context


def test_only_successful_chat_response_creates_conversation_record() -> None:
    success = ProxyResponseEntity(
        status_code=200,
        body='{"choices":[{"message":{"content":"done"}}]}',
        channel_id="channel-123",
        channel_name="primary",
        upstream_model="gpt-4o-upstream",
    )
    service, logs, records, context = service_for(FakeGateway(response=success))

    status, _ = service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}',
        {},
        context,
    )

    assert status == 200
    assert len(logs.entries) == 1
    assert len(records.records) == 1
    assert records.candidates == records.records
    record = records.records[0]
    assert record.request_log_id == logs.entries[0].id
    assert record.trace_id == "request-123"
    assert record.api_key_id == "key-123"
    assert record.channel_id == "channel-123"
    assert "hello" in record.request_payload
    assert "done" in record.response_payload

    failed = ProxyResponseEntity(status_code=502, success=False, error_message="upstream unavailable")
    failed_service, _, failed_records, failed_context = service_for(FakeGateway(response=failed))
    failed_service.forward('{"model":"gpt-4o","messages":[]}', {}, failed_context)
    assert failed_records.records == []
    assert failed_records.candidates == []


def test_candidate_intake_failure_does_not_change_successful_response() -> None:
    success = ProxyResponseEntity(
        status_code=200,
        body='{"choices":[{"message":{"content":"done"}}]}',
    )
    service, _, records, context = service_for(
        FakeGateway(response=success), candidate_error=RuntimeError("candidate unavailable"),
    )

    status, result = service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}',
        {}, context,
    )

    assert status == 200
    assert result["choices"][0]["message"]["content"] == "done"
    assert len(records.records) == 1
    assert records.candidates == []

    stream_service, _, stream_records, stream_context = service_for(
        FakeGateway(events=['{"choices":[{"delta":{"content":"done"}}]}', "[DONE]"]),
        candidate_error=RuntimeError("candidate unavailable"),
    )

    async def collect():
        return [event async for event in stream_service.forward_stream(
            '{"model":"gpt-4o","messages":[],"stream":true}', {}, stream_context,
        )]

    events = asyncio.run(collect())
    assert events[-1] == "data: [DONE]\n\n"
    assert len(stream_records.records) == 1
    assert stream_records.candidates == []


def test_blocked_and_persistence_failures_do_not_enqueue_candidates() -> None:
    success = ProxyResponseEntity(
        status_code=200,
        body='{"choices":[{"message":{"content":"done"}}]}',
    )
    blocked_service, _, blocked_records, context = service_for(
        FakeGateway(response=success), security_enabled=True,
    )
    status, _ = blocked_service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}',
        {}, context,
    )
    assert status == 403
    assert blocked_records.records == []
    assert blocked_records.candidates == []

    log_service, _, log_records, log_context = service_for(
        FakeGateway(response=success), log_error=RuntimeError("log unavailable"),
    )
    status, _ = log_service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}',
        {}, log_context,
    )
    assert status == 200
    assert log_records.records == []
    assert log_records.candidates == []

    record_service, _, record_records, record_context = service_for(
        FakeGateway(response=success), record_error=RuntimeError("record unavailable"),
    )
    status, _ = record_service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}',
        {}, record_context,
    )
    assert status == 200
    assert record_records.records == []
    assert record_records.candidates == []


def test_completed_stream_creates_one_conversation_record() -> None:
    service, logs, records, context = service_for(FakeGateway(events=['{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"]))

    async def collect():
        return [event async for event in service.forward_stream(
            '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}],"stream":true}',
            {},
            context,
        )]

    events = asyncio.run(collect())

    assert events[-1] == "data: [DONE]\n\n"
    assert len(logs.entries) == 1
    assert len(records.records) == 1
    assert records.candidates == records.records
    record = records.records[0]
    assert record.request_log_id == logs.entries[0].id
    assert record.stream is True
    assert record.response_payload == (
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        'data: [DONE]\n\n'
    )


def test_failed_stream_and_invalid_success_payload_do_not_create_records() -> None:
    stream_service, _, stream_records, context = service_for(
        FakeGateway(events=['{"choices":[] }'])
    )

    async def collect():
        return [event async for event in stream_service.forward_stream(
            '{"model":"gpt-4o","messages":[],"stream":true}', {}, context,
        )]

    asyncio.run(collect())
    assert stream_records.records == []
    assert stream_records.candidates == []

    invalid_success = ProxyResponseEntity(status_code=200, body="not-json")
    sync_service, _, sync_records, sync_context = service_for(FakeGateway(response=invalid_success))
    status, _ = sync_service.forward('{"model":"gpt-4o","messages":[]}', {}, sync_context)
    assert status == 502
    assert sync_records.records == []

    semantic_failure = ProxyResponseEntity(status_code=200, body='{"error":{"message":"bad upstream"}}')
    semantic_service, _, semantic_records, semantic_context = service_for(FakeGateway(response=semantic_failure))
    status, _ = semantic_service.forward('{"model":"gpt-4o","messages":[]}', {}, semantic_context)
    assert status == 502
    assert semantic_records.records == []

    empty_choices = ProxyResponseEntity(status_code=200, body='{"choices":[]}')
    choices_service, _, choices_records, choices_context = service_for(FakeGateway(response=empty_choices))
    status, _ = choices_service.forward('{"model":"gpt-4o","messages":[]}', {}, choices_context)
    assert status == 502
    assert choices_records.records == []


def test_conversation_record_keeps_full_client_payloads() -> None:
    content = "x" * 70_000
    response = ProxyResponseEntity(
        status_code=200,
        body='{"choices":[{"message":{"content":"' + content + '"}}]}',
    )
    service, _, records, context = service_for(FakeGateway(response=response))

    status, _ = service.forward(
        '{"model":"gpt-4o","messages":[{"role":"user","content":"' + content + '"}]}',
        {},
        context,
    )

    assert status == 200
    assert len(records.records[0].request_payload) > 65_536
    assert len(records.records[0].response_payload) > 65_536


def test_completed_stream_keeps_full_payload() -> None:
    chunk = "x" * 70_000
    service, _, records, context = service_for(FakeGateway(events=[chunk, "[DONE]"]))

    async def collect():
        return [event async for event in service.forward_stream(
            '{"model":"gpt-4o","messages":[],"stream":true}', {}, context,
        )]

    asyncio.run(collect())
    assert len(records.records[0].response_payload) > 65_536
    assert records.records[0].response_payload.endswith("data: [DONE]\n\n")


def test_canceled_stream_does_not_enqueue_candidate() -> None:
    class CancelingGateway(FakeGateway):
        async def forward_stream_async(self, request):
            raise asyncio.CancelledError()
            yield

    service, _, records, context = service_for(CancelingGateway())

    async def collect():
        return [event async for event in service.forward_stream(
            '{"model":"gpt-4o","messages":[],"stream":true}', {}, context,
        )]

    try:
        asyncio.run(collect())
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("Expected stream cancellation to propagate")

    assert records.records == []
    assert records.candidates == []
