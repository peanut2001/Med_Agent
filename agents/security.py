"""Authentication and conversation identity helpers.

The application is designed to sit behind an OAuth/JWT provider.  In
production the provider must be configured and every protected request must
carry a verified identity.  A deliberately explicit development override is
available for local testing only.
"""

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request, status

_jwks_client = None
_jwks_client_url = None


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    claims: dict


def _auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "true").lower() in {"1", "true", "yes", "on"}


def _decode_bearer(token: str) -> CurrentUser:
    """Decode a JWT supplied by an upstream auth system.

    Signature and issuer validation are delegated to PyJWT when configured.
    The application intentionally refuses unsigned tokens in required mode.
    """
    try:
        import jwt  # PyJWT is an optional runtime dependency until auth is configured.
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="JWT validation is not configured") from exc

    jwks_url = os.getenv("AUTH_JWKS_URL")
    secret = os.getenv("AUTH_JWT_SECRET")
    issuer = os.getenv("AUTH_JWT_ISSUER")
    audience = os.getenv("AUTH_JWT_AUDIENCE")
    if _auth_required() and (not issuer or not audience):
        raise HTTPException(status_code=503, detail="AUTH_JWT_ISSUER and AUTH_JWT_AUDIENCE are required")
    default_algorithms = "RS256" if jwks_url else "HS256"
    algorithms = [item.strip() for item in os.getenv("AUTH_JWT_ALGORITHMS", default_algorithms).split(",") if item.strip()]
    options = {"verify_aud": bool(audience)}
    kwargs = {"algorithms": algorithms, "options": options}
    if jwks_url:
        try:
            from jwt import PyJWKClient
            global _jwks_client, _jwks_client_url
            if _jwks_client is None or _jwks_client_url != jwks_url:
                _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
                _jwks_client_url = jwks_url
            key = _jwks_client.get_signing_key_from_jwt(token).key
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unable to verify signing key") from exc
    elif secret:
        key = secret
    else:
        raise HTTPException(status_code=503, detail="Configure AUTH_JWKS_URL or AUTH_JWT_SECRET")
    try:
        claims = jwt.decode(
            token,
            key,
            issuer=issuer or None,
            audience=audience or None,
            **kwargs,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has no subject")
    return CurrentUser(user_id=str(user_id), claims=claims)


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
) -> CurrentUser:
    """FastAPI dependency used by protected endpoints.

    ``X-User-ID`` is only accepted when ``AUTH_REQUIRED=false`` and should be
    used exclusively by local development or a trusted test harness.
    """
    if not _auth_required() and x_user_id:
        return CurrentUser(user_id=x_user_id, claims={"sub": x_user_id, "dev": True})
    if not authorization or not authorization.lower().startswith("bearer "):
        if not _auth_required() and x_user_id:
            return CurrentUser(user_id=x_user_id, claims={"sub": x_user_id, "dev": True})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return _decode_bearer(authorization.split(" ", 1)[1].strip())


def resolve_conversation_id(request: Request, requested: Optional[str] = None) -> str:
    """Resolve a conversation ID while keeping it server-controlled.

    A caller can continue an existing conversation by sending the ID in the
    request body/form.  Ownership is checked by the validation/checkpoint
    layer; new IDs are generated server-side.
    """
    return requested or request.cookies.get("conversation_id") or os.urandom(16).hex()
