from types import SimpleNamespace

from app.application.services.misc_services import ProxyService
from app.domain.entities import (
    ChannelEntity,
    ProxyCallContext,
    ProxyRequestEntity,
    ProxyResponseEntity,
)
from app.domain.gateway import _build_headers


class FakeGateway:
    def __init__(self):
        self.request = None

    def forward(self, request):
        self.request = request
        return ProxyResponseEntity(status_code=200, body='{"ok": true}')


class FakeLogRepository:
    def __init__(self):
        self.entries = []

    def insert_log(self, entry):
        self.entries.append(entry)


def test_proxy_service_consumes_verified_call_context() -> None:
    gateway = FakeGateway()
    logs = FakeLogRepository()
    context = ProxyCallContext(
        request_id="request-123",
        api_key_id="key-123",
        api_key_name="desktop-client",
        client_ip="127.0.0.1",
    )
    service = ProxyService(gateway, None, SimpleNamespace(enabled=False), logs)

    status, body = service.forward('{"model":"gpt-4o","messages":[]}', {}, context)

    assert (status, body) == (200, {"ok": True})
    assert gateway.request.context is context
    assert gateway.request.api_key is None
    assert logs.entries[0].trace_id == "request-123"
    assert logs.entries[0].api_key_id == "key-123"
    assert logs.entries[0].api_key_name == "desktop-client"


def test_gateway_sends_only_the_server_request_id() -> None:
    context = ProxyCallContext(request_id="request-123")
    request = ProxyRequestEntity(model="gpt-4o", body={}, context=context)
    channel = ChannelEntity(type="openai", api_key="upstream-secret")

    headers = _build_headers(channel, request)

    assert headers["X-Request-ID"] == "request-123"
    assert headers["Authorization"] == "Bearer upstream-secret"
