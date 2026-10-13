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
Every session check also verifies that the account is still enabled, so
disabling an account immediately blocks its existing sessions.

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
Omitting `conversation_id` starts a new conversation; continuing an existing
conversation requires its explicit ID. A previous conversation cookie is not
used as a fallback.

## Single-container concurrency

The default concurrency settings are:

```text
MAX_CONCURRENT_AGENT_REQUESTS=4
MAX_QUEUED_REQUESTS=16
REQUEST_QUEUE_TIMEOUT_SECONDS=15
MAX_CONCURRENT_IMAGE_INFERENCES=1
MAX_AUDIO_UPLOAD_SIZE_MB=25
PRIVATE_ARTIFACT_TTL_SECONDS=86400
EXECUTION_TRACE_TTL_SECONDS=3600
EXECUTION_TRACE_MAX_RECORDS=1000
```

Requests for the same `user_id + conversation_id` are serialized to protect
LangGraph checkpoint updates. Different conversations may run concurrently up
to the global request limit. Image inference has a separate conservative limit
because the model objects are shared by the process.
Expensive HTTP routes (chat, uploads, speech, reviews and conversation deletion)
share an asynchronous admission queue before entering the worker pool. At most
`MAX_CONCURRENT_AGENT_REQUESTS` requests enter these routes at once, capped to
leave eight shared worker tokens available where the pool size permits. Up to
`MAX_QUEUED_REQUESTS` additional requests wait without consuming worker threads.
Full queues and waits exceeding `REQUEST_QUEUE_TIMEOUT_SECONDS` return HTTP 429
with `Retry-After`. Health checks, authentication and trace cancellation bypass
this queue, so queued chat traffic does not prevent checking or stopping work.
Chat execution and history writes are also serialized against conversation
deletion. Deleting a conversation removes its LangGraph checkpoint state.
It also invalidates the conversation's review records and their image access.
Review submissions require an existing owned conversation and are serialized
against deletion. A review ID can create at most one confirmation message;
retries return the original decision and comments. Existing SQLite history
databases receive the deduplication column and index automatically at startup.
Image-analysis messages also store their review request ID. History responses
restore review controls only when the record still exists, belongs to the
authenticated user and conversation, and remains pending. Resolved or expired
records never restore actionable controls. In the default memory mode, service
restarts still invalidate review records; persistent reviews require PostgreSQL.
Completed in-memory conversations retain only their latest checkpoint, and
the checkpoint message list is trimmed to `max_conversation_history` (20 by
default), rather than only trimming the HTTP response.
Failed and cancelled graph turns restore the previous completed state and
discard failed-turn messages and pending tasks. The in-memory saver also
compacts the restored state to one checkpoint before accepting a retry.

Image uploads are limited to 5 MiB; audio uploads default to 25 MiB and can be
configured with `MAX_AUDIO_UPLOAD_SIZE_MB`. Multipart requests are bounded
before parsing, including requests without `Content-Length`, with 64 KiB of
allowance for headers and form fields. Individual file reads are also bounded.
Oversized uploads return HTTP 413 before model inference or transcription.

Docker build contexts exclude local SQLite databases and their journal files,
as well as data backup directories. Runtime account and conversation databases
must be supplied through the data volume, rather than baked into an image.

Uploaded source files, generated images, and generated audio are private
server-side files. The application does not expose `/data` or `/uploads` as
static directories. A generated medical image is available only from
`GET /validations/{validation_id}/image`, which authenticates the caller and
checks ownership before resolving the stored path. Expired private artifacts
are removed after the configured TTL.

Without `CHECKPOINT_DATABASE_URL`, checkpoint state remains process-local and
is lost on restart. The next chat request restores the most recent owned
SQLite history window when the checkpoint has no messages, including persisted
review decisions, before invoking the model. Existing checkpoints are not
re-seeded, and recovery never reloads temporary source images or pending tasks.
This mode supports one Uvicorn process only. Configure
PostgreSQL before adding workers or application containers.

## Execution trace visibility

The frontend creates an authenticated trace with `POST /traces` before each
agent request and polls `GET /traces/{trace_id}` while the graph is running.
Trace records are scoped to the authenticated user and contain only node IDs,
status, routing metadata, timestamps, and durations. User prompts, retrieved
medical documents, model outputs, tokens, and credentials are not stored in
the trace repository. The in-memory trace repository is bounded by TTL and
record count and is intentionally limited to the single-process deployment.
