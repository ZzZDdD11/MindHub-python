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

    def create_if_absent(self, record):
        self.records.append(record)
        return True


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


def service_for(gateway):
    logs = FakeLogRepository()
    records = FakeConversationRecordRepository()
    service = ProxyService(
        gateway, None, SimpleNamespace(enabled=False), logs,
        conversation_record_repository=records,
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
