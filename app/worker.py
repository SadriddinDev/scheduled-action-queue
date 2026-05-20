"""
Background worker: polls DB for due tasks, claims them with SELECT FOR UPDATE SKIP LOCKED,
executes the action handler, and applies retry / failure logic.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import Task, TaskLog
from app import action_handlers

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5   # seconds between polls
BATCH_SIZE = 10     # tasks claimed per poll cycle


async def _claim_due_tasks() -> list[Task]:
    """
    Open a short transaction, lock due pending rows with SKIP LOCKED,
    flip them to 'running', commit. Returns the claimed tasks.

    SKIP LOCKED ensures concurrent workers never pick the same row.
    The transaction is kept short so we hold the row lock for milliseconds.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .where(Task.status == "pending", Task.run_at <= datetime.now(timezone.utc))
            .with_for_update(skip_locked=True)
            .order_by(Task.run_at)
            .limit(BATCH_SIZE)
        )
        tasks = list(result.scalars().all())

        for task in tasks:
            task.status = "running"
            task.updated_at = datetime.now(timezone.utc)

        await session.commit()

        # Detach so objects can be used outside this session
        for task in tasks:
            session.expunge(task)

    return tasks


async def _execute_task(task: Task) -> None:
    """Run one task, write a log entry, update status / schedule retry on failure."""
    attempt = task.retry_count + 1
    started_at = datetime.now(timezone.utc)

    # ── Write "started" log ──────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        log = TaskLog(
            task_id=task.id,
            attempt=attempt,
            status="started",
            started_at=started_at,
        )
        session.add(log)
        await session.commit()
        log_id = log.id

    # ── Execute handler (outside any DB transaction) ─────────────────────────
    error_msg: str | None = None
    success = False
    try:
        await action_handlers.execute(task.action, task.payload)
        success = True
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Task %s attempt %d failed: %s", task.id, attempt, exc)

    finished_at = datetime.now(timezone.utc)

    # ── Persist result ────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(TaskLog)
            .where(TaskLog.id == log_id)
            .values(
                status="success" if success else "failed",
                error=error_msg,
                finished_at=finished_at,
            )
        )

        if success:
            await session.execute(
                update(Task)
                .where(Task.id == task.id)
                .values(status="completed", updated_at=finished_at)
            )
        else:
            new_retry_count = attempt  # == task.retry_count + 1
            if new_retry_count < task.max_retries:
                # Exponential backoff: 2^n minutes (60s, 120s, 240s, …)
                backoff = timedelta(seconds=(2 ** new_retry_count) * 60)
                next_run_at = finished_at + backoff
                await session.execute(
                    update(Task)
                    .where(Task.id == task.id)
                    .values(
                        status="pending",
                        retry_count=new_retry_count,
                        run_at=next_run_at,
                        updated_at=finished_at,
                    )
                )
                logger.info(
                    "Task %s retry %d/%d scheduled at %s",
                    task.id, new_retry_count, task.max_retries, next_run_at,
                )
            else:
                await session.execute(
                    update(Task)
                    .where(Task.id == task.id)
                    .values(
                        status="failed",
                        retry_count=new_retry_count,
                        updated_at=finished_at,
                    )
                )
                logger.warning("Task %s exhausted all %d retries", task.id, task.max_retries)

        await session.commit()


async def worker_loop() -> None:
    logger.info("Worker started — polling every %ds, batch=%d", POLL_INTERVAL, BATCH_SIZE)
    while True:
        try:
            tasks = await _claim_due_tasks()
            if tasks:
                logger.info("Claimed %d task(s)", len(tasks))
                await asyncio.gather(*[_execute_task(t) for t in tasks])
        except Exception:
            logger.exception("Worker poll cycle error")

        await asyncio.sleep(POLL_INTERVAL)
