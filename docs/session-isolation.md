# Session isolation configuration

Protected chat endpoints use the authenticated JWT subject (`sub`) as the
user identity and combine it with a server-generated `conversation_id` for the
LangGraph thread ID.

For the current small local test deployment, use the built-in SQLite login:

```text
AUTH_MODE=local
AUTH_REQUIRED=true
LOCAL_AUTH_DB=data/local_auth.db
LOCAL_AUTH_USERS={"alice":"change-this-password","bob":"change-this-password"}
COOKIE_SECURE=false
```

`LOCAL_AUTH_USERS` is only used to bootstrap accounts; passwords are stored as
PBKDF2 hashes in SQLite. Log in through `POST /auth/login`, then the server
uses the HttpOnly `med_agent_session` cookie for protected endpoints.

For a production deployment with an external identity provider, use:

```text
AUTH_REQUIRED=true
AUTH_MODE=oidc
AUTH_JWKS_URL=https://issuer.example.com/.well-known/jwks.json
AUTH_JWT_ALGORITHMS=RS256
AUTH_JWT_ISSUER=<issuer>
AUTH_JWT_AUDIENCE=<audience>
CHECKPOINT_DATABASE_URL=postgresql+psycopg://user:password@host/dbname
COOKIE_SECURE=true
```

`AUTH_JWKS_URL` is the preferred OAuth/OIDC setup. For an internal service
that issues HMAC-signed tokens, use `AUTH_JWT_SECRET` and set
`AUTH_JWT_ALGORITHMS=HS256` instead.

For a temporary no-auth smoke test only, set `AUTH_MODE=disabled` and
`AUTH_REQUIRED=false`, then send an `X-User-ID` header. This mode must not be
used when multiple people can reach the service.

The frontend sends `conversation_id` and `validation_id` as part of the API
contract. The backend always verifies ownership against the authenticated
user before reading or resolving state.
