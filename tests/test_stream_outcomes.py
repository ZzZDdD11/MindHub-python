import asyncio
from types import SimpleNamespace

from app.application.services.misc_services import ProxyService
from app.domain.entities import ProxyCallContext
from app.domain.gateway import UpstreamStreamError


class FakeStreamGateway:
    def __init__(self, events):
        self.events = events
        self.request = None

    async def forward_stream_async(self, request):
        self.request = request
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event


class FakeLogRepository:
    def __init__(self):
        self.entries = []

    def insert_log(self, entry):
        self.entries.append(entry)


def collect(stream):
    async def run():
        return [event async for event in stream]

    return asyncio.run(run())


def service_for(events):
    logs = FakeLogRepository()
    service = ProxyService(
        FakeStreamGateway(events), None, SimpleNamespace(enabled=False), logs,
    )
    context = ProxyCallContext(request_id="request-123", api_key_id="key-123")
    return service, logs, context


def test_completed_stream_emits_done_once_and_records_completion() -> None:
    service, logs, context = service_for(['{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"])

    events = collect(service.forward_stream('{"model":"gpt-4o","stream":true}', {}, context))

    assert events[-1] == "data: [DONE]\n\n"
    assert events.count("data: [DONE]\n\n") == 1
    assert logs.entries[0].stream_outcome == "completed"
    assert logs.entries[0].status_code == 200


def test_failed_stream_does_not_emit_done() -> None:
    service, logs, context = service_for([UpstreamStreamError("upstream unavailable", 502)])

    events = collect(service.forward_stream('{"model":"gpt-4o","stream":true}', {}, context))

    assert len(events) == 1
    assert "upstream_error" in events[0]
    assert "[DONE]" not in events[0]
    assert logs.entries[0].stream_outcome == "failed"
    assert logs.entries[0].status_code == 502


def test_eof_without_done_is_failed() -> None:
    service, logs, context = service_for(['{"choices":[]}'])

    events = collect(service.forward_stream('{"model":"gpt-4o","stream":true}', {}, context))

    assert "[DONE]" not in "".join(events)
    assert logs.entries[0].stream_outcome == "failed"
    assert logs.entries[0].status_code == 502
