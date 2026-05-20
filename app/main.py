import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task
from app.schemas import TaskCreate, TaskResponse, TaskDetailResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application started")
    yield
    logger.info("Application shut down")


app = FastAPI(
    title="Scheduled Action Queue",
    description="Durable scheduled task queue with retry logic",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Schedule a new task. Provide idempotency_key to prevent duplicate scheduling."""
    task = Task(
        action=body.action,
        payload=body.payload,
        run_at=body.run_at,
        idempotency_key=body.idempotency_key,
        max_retries=body.max_retries,
    )
    db.add(task)
    try:
        await db.commit()
        await db.refresh(task)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency key already exists")
    return task


@app.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None, description=f"Filter by status: {VALID_STATUSES}"),
    db: AsyncSession = Depends(get_db),
):
    """List all tasks, optionally filtered by status."""
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Valid values: {sorted(VALID_STATUSES)}",
        )
    q = select(Task).order_by(Task.run_at)
    if status:
        q = q.where(Task.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@app.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a single task with its full execution history."""
    result = await db.execute(
        select(Task).options(selectinload(Task.logs)).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.delete("/tasks/{task_id}", status_code=204)
async def cancel_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Cancel a pending task. Returns 409 if task is already running/completed/failed."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel task with status '{task.status}'",
        )
    task.status = "cancelled"
    await db.commit()
