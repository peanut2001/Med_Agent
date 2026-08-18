# Session isolation configuration

Protected chat endpoints use the authenticated JWT subject (`sub`) as the
user identity and combine it with a server-generated `conversation_id` for the
LangGraph thread ID.

Production settings:

```text
AUTH_REQUIRED=true
AUTH_JWKS_URL=https://issuer.example.com/.well-known/jwks.json
AUTH_JWT_ALGORITHMS=RS256
AUTH_JWT_ISSUER=<issuer>
AUTH_JWT_AUDIENCE=<audience>
CHECKPOINT_DATABASE_URL=postgresql+psycopg://user:password@host/dbname
```

`AUTH_JWKS_URL` is the preferred OAuth/OIDC setup. For an internal service
that issues HMAC-signed tokens, use `AUTH_JWT_SECRET` and set
`AUTH_JWT_ALGORITHMS=HS256` instead.

For a local trusted test harness only, set `AUTH_REQUIRED=false` and send an
`X-User-ID` header. This mode uses the in-process checkpoint and validation
store when no PostgreSQL URL is configured and must not be used in production.

The frontend sends `conversation_id` and `validation_id` as part of the API
contract. The backend always verifies ownership against the authenticated
user before reading or resolving state.
