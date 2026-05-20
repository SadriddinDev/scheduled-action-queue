"""
Action handler registry.

Register a handler:
    @register("my_action")
    async def handle_my_action(payload: dict) -> None:
        ...

Unknown actions raise ValueError and the task is immediately marked failed.
"""
import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

HandlerFunc = Callable[[dict[str, Any]], Awaitable[None]]

_registry: dict[str, HandlerFunc] = {}


def register(action: str):
    def decorator(fn: HandlerFunc) -> HandlerFunc:
        _registry[action] = fn
        return fn
    return decorator


async def execute(action: str, payload: dict[str, Any]) -> None:
    handler = _registry.get(action)
    if handler is None:
        raise ValueError(f"No handler registered for action: {action!r}")
    await handler(payload)


# ---------------------------------------------------------------------------
# Built-in demo handlers
# ---------------------------------------------------------------------------

@register("send_email")
async def _handle_send_email(payload: dict[str, Any]) -> None:
    logger.info("[send_email] to=%s subject=%r", payload.get("to"), payload.get("subject"))
    await asyncio.sleep(0.05)


@register("http_request")
async def _handle_http_request(payload: dict[str, Any]) -> None:
    logger.info("[http_request] %s %s", payload.get("method", "GET"), payload.get("url"))
    await asyncio.sleep(0.05)


@register("noop")
async def _handle_noop(payload: dict[str, Any]) -> None:
    logger.info("[noop] %s", payload)


@register("fail_always")
async def _handle_fail_always(payload: dict[str, Any]) -> None:
    """Used in tests/demos to exercise the retry path."""
    raise RuntimeError(payload.get("reason", "intentional failure"))
