import re

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient

from app.api.middleware.request_context import RequestContextMiddleware
from app.main import app as application
from app.main import global_exception_handler

REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def assert_server_request_id(response) -> str:
    request_id = response.headers["x-request-id"]
    assert REQUEST_ID_PATTERN.fullmatch(request_id)
    return request_id


def test_request_context_is_server_generated_and_available_to_routes() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/context")
    async def context(request: Request):
        return {"request_id": request.state.request_id}

    response = TestClient(app).get("/context", headers={"X-Request-ID": "client-controlled"})

    assert response.status_code == 200
    assert response.json()["request_id"] == assert_server_request_id(response)
    assert response.headers["x-request-id"] != "client-controlled"


def test_request_context_replaces_downstream_request_id_header() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/response")
    async def response():
        return Response("ok", headers={"X-Request-ID": "downstream-controlled"})

    result = TestClient(app).get("/response")

    assert result.status_code == 200
    assert assert_server_request_id(result) != "downstream-controlled"


def test_request_context_preserves_sse_body() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/events")
    async def events():
        async def event_stream():
            yield "data: first\n\n"
            yield "data: second\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    response = TestClient(app).get("/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert_server_request_id(response)
    assert response.text == "data: first\n\ndata: second\n\n"


def test_application_health_response_includes_request_id() -> None:
    response = TestClient(application).get("/health")

    assert response.status_code == 200
    assert_server_request_id(response)


def test_application_auth_rejection_includes_request_id() -> None:
    response = TestClient(application).post("/v1/chat/completions")

    assert response.status_code == 401
    assert_server_request_id(response)


def test_exception_response_includes_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, global_exception_handler)

    @app.get("/error")
    async def error():
        raise RuntimeError("not safe for clients")

    response = TestClient(app, raise_server_exceptions=False).get("/error")

    assert response.status_code == 500
    assert_server_request_id(response)
    assert response.json()["info"] == "Internal server error"
