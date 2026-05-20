# Scheduled Action Queue

A durable, concurrent-safe scheduled task queue built with **FastAPI** and **PostgreSQL**. Schedule tasks to run at a future time — the background worker picks them up, executes the registered action handler, and retries on failure with exponential backoff. Every attempt is logged.

## Features

- **Schedule tasks** via REST API with a future `run_at` timestamp
- **Durable** — tasks survive server restarts (stored in PostgreSQL, never in memory)
- **Concurrent-safe** — multiple workers can run in parallel without processing the same task twice (`SELECT FOR UPDATE SKIP LOCKED`)
- **Retry with exponential backoff** — up to N retries, with backoff of 2ⁿ × 60 seconds between attempts
- **Execution history** — every attempt is logged with status, error, start and finish time
- **Idempotency** — optional `idempotency_key` prevents duplicate task scheduling
- **Observable** — each task has a clear status lifecycle: `pending → running → completed / failed / cancelled`

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2 (async) |
| Driver | asyncpg |
| Worker | Separate Docker container (`run_worker.py`) |
| Migrations | Alembic (separate `migrate` container) |
| Container | Docker + Docker Compose |

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/tasks` | Schedule a new task |
| `GET` | `/tasks` | List all tasks (filter by `?status=`) |
| `GET` | `/tasks/{id}` | Get task detail + execution history |
| `DELETE` | `/tasks/{id}` | Cancel a pending task |

### Create a task

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "action": "send_email",
    "payload": { "to": "user@example.com", "subject": "Welcome" },
    "run_at": "2026-05-20T10:00:00Z",
    "max_retries": 3,
    "idempotency_key": "welcome-email-user-42"
  }'
```

### Task statuses

```
pending → running → completed
                  → failed     (all retries exhausted)
pending → cancelled            (manually cancelled before execution)
```

## Project Structure

```
.
├── run_worker.py           # Worker entrypoint (runs as a separate container)
├── alembic.ini             # Alembic config (URL is read from DATABASE_URL env var)
├── alembic/
│   ├── env.py              # Async-compatible migration environment
│   └── versions/
│       └── 0001_initial_schema.py
├── docker-compose.yml
├── Dockerfile
└── app/
    ├── main.py             # FastAPI routes + app lifespan
    ├── models.py           # SQLAlchemy models (Task, TaskLog)
    ├── schemas.py          # Pydantic request/response schemas
    ├── database.py         # Async engine + session factory
    ├── worker.py           # Background polling worker logic
    └── action_handlers.py  # Action handler registry
```

## Deployment Architecture

```
docker-compose
├── db       — PostgreSQL 16
├── migrate  — alembic upgrade head   (runs once, exits)
├── api      — uvicorn app.main:app   (HTTP, port 8000)
└── worker   — python run_worker.py   (no open port)
```

All four services are built from the **same image** but run different commands. `api` and `worker` only start after `migrate` exits successfully (`service_completed_successfully`), so the schema is always up to date before any traffic hits the database. The worker uses `SELECT FOR UPDATE SKIP LOCKED`, so you can safely scale it horizontally:

```bash
docker compose up --scale worker=3
```

## How the Worker Works

The worker runs as a **separate process** (`run_worker.py`) inside its own Docker container — completely isolated from the API process.

1. Every 5 seconds, poll for due tasks:
   ```sql
   SELECT * FROM tasks
   WHERE status = 'pending' AND run_at <= NOW()
   FOR UPDATE SKIP LOCKED
   LIMIT 10;
   ```
2. Mark claimed tasks as `running` and commit (releases the row lock immediately).
3. Execute the action handler outside the transaction (so slow tasks don't hold locks).
4. On success → `completed`. On failure → schedule retry with backoff or mark `failed`.

`SKIP LOCKED` is the key to concurrent safety: each worker atomically skips rows already locked by another worker, so no task is ever processed twice. Heavy worker load does not affect API latency, and vice versa.

## Retry Logic

| Attempt | Backoff |
|---|---|
| 1st retry | 2 min |
| 2nd retry | 4 min |
| 3rd retry | 8 min |

After `max_retries` attempts the task is marked `failed`.

## Adding a Custom Handler

Register your handler in `app/action_handlers.py`:

```python
@register("charge_card")
async def handle_charge_card(payload: dict) -> None:
    await payment_gateway.charge(payload["user_id"], payload["amount_cents"])
```

Then schedule it via the API:

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"action": "charge_card", "payload": {"user_id": 7, "amount_cents": 4999}, "run_at": "2026-05-20T12:00:00Z"}'
```

## Running Locally

**With Docker Compose (recommended):**

```bash
docker compose up --build
```

This starts three containers: `db`, `api` (port 8000), and `worker`.

To run multiple workers in parallel:

```bash
docker compose up --build --scale worker=3
```

**With a local PostgreSQL:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+asyncpg://USER@localhost:5432/taskqueue"

# Apply migrations first
alembic upgrade head

# Terminal 1 — API
uvicorn app.main:app --reload

# Terminal 2 — Worker
python run_worker.py
```

## Database Migrations

Migrations live in `alembic/versions/`. After changing a model:

```bash
# Generate a new migration (requires a running DB)
alembic revision --autogenerate -m "describe your change"

# Review the generated file in alembic/versions/, then apply:
alembic upgrade head

# Roll back one step:
alembic downgrade -1
```

In Docker, the `migrate` service runs `alembic upgrade head` automatically on every `docker compose up`.

Interactive API docs available at `http://localhost:8000/docs`.

## Running Tests

```bash
# Start the server first, then:
python send-request-test.py
```

The test script covers: happy path, retry exhaustion, idempotency, cancel, and list filtering.
