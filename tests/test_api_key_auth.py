from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.middleware.auth import ApiKeyAuthMiddleware
from app.domain.entities import ApiKeyEntity


class FakeApiKeyRepository:
    def __init__(self, api_key: ApiKeyEntity | None):
        self.api_key = api_key
        self.lookups: list[str] = []

    def get_api_key_by_key(self, key: str) -> ApiKeyEntity | None:
        self.lookups.append(key)
        return self.api_key


def create_app(repository: FakeApiKeyRepository) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ApiKeyAuthMiddleware, repository=repository)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        return {
            "api_key_id": request.state.api_key_id,
            "api_key_name": request.state.api_key_name,
            "has_raw_key": hasattr(request.state, "api_key"),
        }

    return app


def test_valid_api_key_exposes_verified_identity_only() -> None:
    repository = FakeApiKeyRepository(ApiKeyEntity(id="key-1", name="desktop-client"))

    response = TestClient(create_app(repository)).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-secret"},
    )

    assert response.status_code == 200
    assert repository.lookups == ["valid-secret"]
    assert response.json() == {
        "api_key_id": "key-1",
        "api_key_name": "desktop-client",
        "has_raw_key": False,
    }


def test_unknown_api_key_is_rejected() -> None:
    repository = FakeApiKeyRepository(None)

    response = TestClient(create_app(repository)).post(
        "/v1/chat/completions",
        headers={"x-api-key": "unknown-secret"},
    )

    assert response.status_code == 401
    assert repository.lookups == ["unknown-secret"]
