"""API key authentication middleware."""
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.infrastructure.repositories.channel_repo import ChannelRepository

logger = logging.getLogger(__name__)

PROTECTED_PREFIXES = (
    "/v1/chat/completions", "/v1/completions", "/v1/responses", "/v1/embeddings",
    "/v1/images/generations", "/v1/audio/transcriptions", "/v1/audio/speech", "/v1/messages",
)

WHITELIST_PREFIXES = (
    "/health", "/api/v1/", "/api/mcp", "/v1/models",
)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, repository: ChannelRepository | None = None):
        super().__init__(app)
        self.repository = repository or ChannelRepository()

    async def dispatch(self, request, call_next):
        path = request.url.path

        for wl in WHITELIST_PREFIXES:
            if path.startswith(wl):
                return await call_next(request)

        needs_auth = any(path.startswith(p) for p in PROTECTED_PREFIXES)
        if not needs_auth:
            return await call_next(request)

        api_key = self._extract_api_key(request)
        if not api_key:
            logger.warning("Missing API key for path: %s", path)
            return self._authentication_error("Missing API key")

        try:
            verified_key = self.repository.get_api_key_by_key(api_key)
        except Exception:
            logger.exception("API key lookup failed")
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Authentication service unavailable", "type": "server_error"}},
            )

        if not verified_key or not verified_key.id:
            logger.warning("Rejected invalid API key for path: %s", path)
            return self._authentication_error("Invalid API key")

        request.state.api_key_id = verified_key.id
        request.state.api_key_name = verified_key.name
        return await call_next(request)

    @staticmethod
    def _authentication_error(message: str):
        return JSONResponse(
            status_code=401,
            content={"error": {"message": message, "type": "authentication_error"}},
        )

    def _extract_api_key(self, request):
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            key = auth[7:].strip()
            if key:
                return key
        x_api_key = request.headers.get("x-api-key")
        if x_api_key and x_api_key.strip():
            return x_api_key.strip()
        return None
