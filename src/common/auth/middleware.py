"""JWT verification middleware. Validates Bearer token and sets request.state.auth."""

import json
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from starlette.types import ASGIApp, Receive, Scope, Send

from src.common.auth.config import AuthConfig
from src.models.auth_models import AuthContext

_OWNER_ROLES = frozenset({"owner", "tenant_owner"})


class AuthMiddleware:
    """ASGI JWT gate. Public paths pass through unbuffered so Buzz SSE can stream."""

    def __init__(self, app: ASGIApp, config: AuthConfig) -> None:
        self.app = app
        self._config = config
        if config.algorithm.upper() == "RS256" and config.public_key_path:
            with open(config.public_key_path) as f:
                self._verify_key_cached = f.read()
        else:
            self._verify_key_cached = config.secret_key

    def _is_public_path(self, path: str) -> bool:
        """Check if path is in public_paths (exact or prefix)."""
        for p in self._config.public_paths:
            if path == p or path.rstrip("/") == p.rstrip("/"):
                return True
            if p.endswith("/") and path.startswith(p):
                return True
            if not p.endswith("/") and path.startswith(p + "/"):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        scope.setdefault("state", {})
        if self._is_public_path(path):
            scope["state"]["auth"] = None
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        auth_header = headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            await self._unauthorized(send, "Missing or invalid Authorization header")
            return

        token = auth_header[7:].strip()
        if not token:
            await self._unauthorized(send, "Missing Bearer token")
            return

        try:
            payload = jwt.decode(
                token,
                self._verify_key_cached,
                algorithms=[self._config.algorithm],
                audience=self._config.audience,
                issuer=self._config.issuer,
            )
        except JWTError as e:
            await self._unauthorized(send, "Invalid or expired token", details=str(e))
            return

        sub = payload.get("sub")
        tenant_id_raw = payload.get("tenant_id")
        role = payload.get("role")
        if not sub:
            await self._unauthorized(send, "Token missing sub")
            return

        try:
            user_id = UUID(sub)
        except (ValueError, TypeError):
            await self._unauthorized(send, "Invalid sub in token")
            return

        tenant_id: Optional[UUID] = None
        if tenant_id_raw is not None:
            try:
                tenant_id = UUID(str(tenant_id_raw))
            except (ValueError, TypeError):
                pass

        owner_id: Optional[UUID] = None
        if (role or "").strip().lower() in _OWNER_ROLES:
            owner_id_raw = payload.get("owner_id") or sub
            try:
                owner_id = UUID(str(owner_id_raw))
            except (ValueError, TypeError):
                owner_id = user_id

        scope["state"]["auth"] = AuthContext.model_validate(
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": role if role else "tenant_admin",
                "owner_id": owner_id,
            }
        )
        await self.app(scope, receive, send)

    async def _unauthorized(self, send: Send, message: str, details: Optional[str] = None) -> None:
        error: dict[str, object] = {"code": "UNAUTHORIZED", "message": message}
        if details:
            error["details"] = details
        body = json.dumps({"status": "error", "error": error}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
