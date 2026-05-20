import requests
from datetime import datetime, timezone, timedelta

BASE = "http://localhost:8000"


def create_task(action, payload, run_at=None, idempotency_key=None, max_retries=3):
    """POST /tasks — create a new task."""
    if run_at is None:
        run_at = datetime.now(timezone.utc) - timedelta(seconds=3)
    if isinstance(run_at, datetime):
        run_at = run_at.isoformat()

    body = {"action": action, "payload": payload, "run_at": run_at, "max_retries": max_retries}
    if idempotency_key:
        body["idempotency_key"] = idempotency_key

    r = requests.post(f"{BASE}/tasks", json=body)
    print(f"[create_task] {r.status_code} → action={action}")
    print(r.json())
    return r


def list_tasks(status=None):
    """GET /tasks — list all tasks, with an optional status filter."""
    params = {}
    if status:
        params["status"] = status

    r = requests.get(f"{BASE}/tasks", params=params)
    tasks = r.json()
    label = f"status={status}" if status else "all"
    print(f"[list_tasks] {r.status_code} → {label}: {len(tasks)} task(s)")
    for t in tasks:
        print(f"  {t['id']}  action={t['action']:<15} status={t['status']:<12} run_at={t['run_at']}")
    return r


def get_task(task_id):
    """GET /tasks/{id} — get a single task with its execution history."""
    r = requests.get(f"{BASE}/tasks/{task_id}")
    print(f"[get_task] {r.status_code} → id={task_id}")
    if r.status_code == 200:
        data = r.json()
        print(f"  action={data['action']}  status={data['status']}  retry_count={data['retry_count']}/{data['max_retries']}")
        print(f"  logs ({len(data['logs'])}):")
        for log in data["logs"]:
            err = f"  error={log['error']!r}" if log["error"] else ""
            print(f"    attempt={log['attempt']} status={log['status']}{err}")
    else:
        print(f"  {r.json()}")
    return r


def cancel_task(task_id):
    """DELETE /tasks/{id} — cancel a pending task."""
    r = requests.delete(f"{BASE}/tasks/{task_id}")
    print(f"[cancel_task] {r.status_code} → id={task_id}")
    if r.status_code != 204:
        print(f"  {r.json()}")
    return r


# ---------------------------------------------------------------------------
# Ready-made demo scenarios
# ---------------------------------------------------------------------------

def demo_happy_path():
    """Simple successful task: create → worker executes → inspect result."""
    print("\n" + "="*60)
    print("DEMO: Happy path — noop task")
    print("="*60)

    r = create_task("noop", {"msg": "salom"})
    task_id = r.json()["id"]

    print("\n--- Immediate state ---")
    get_task(task_id)

    print("\n--- Waiting 8 seconds for the worker to run ---")
    import time; time.sleep(8)

    print("\n--- After worker execution ---")
    get_task(task_id)


def demo_retry():
    """Observe retry logic using the fail_always action."""
    print("\n" + "="*60)
    print("DEMO: Retry path — fail_always, max_retries=2")
    print("="*60)

    r = create_task("fail_always", {"reason": "demo xato"}, max_retries=2)
    task_id = r.json()["id"]

    import time; time.sleep(8)

    print("\n--- After attempt 1 ---")
    get_task(task_id)


def demo_idempotency():
    """Sending the same idempotency_key twice should return 409."""
    print("\n" + "="*60)
    print("DEMO: Idempotency — bir xil key ikki marta")
    print("="*60)

    key = "order-xyz-002"
    print("\nFirst request:")
    create_task("noop", {"order": "xyz-001"}, idempotency_key=key)

    print("\nSecond request (same key):")
    create_task("noop", {"order": "xyz-001"}, idempotency_key=key)


def demo_cancel():
    """Cancel a future task before it runs."""
    print("\n" + "="*60)
    print("DEMO: Cancel — future task bekor qilish")
    print("="*60)

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    r = create_task("send_email", {"to": "u@example.com", "subject": "Test"}, run_at=future)
    task_id = r.json()["id"]

    print("\n--- Cancelling ---")
    cancel_task(task_id)

    print("\n--- Cancelled task ---")
    get_task(task_id)


def demo_list_filters():
    """Filter tasks by each status value."""
    print("\n" + "="*60)
    print("DEMO: List with filters")
    print("="*60)

    for status in [None, "pending", "completed", "failed", "cancelled"]:
        list_tasks(status)
        print()


if __name__ == "__main__":
    demo_happy_path()
    demo_idempotency()
    demo_cancel()
    demo_list_filters()
    demo_retry()
