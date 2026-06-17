"""Async pub/sub event bus — extracted from auto-apply-agent's EventBus pattern."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger("radar.event_bus")

Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    def subscribe(self, event: str, handler: Handler) -> None:
        self._subscribers[event].append(handler)
        logger.debug("Subscribed to '%s': %s", event, handler.__name__)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        await self._queue.put((event, data))

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._process())
        logger.info("Event bus started")

    async def stop(self) -> None:
        self._running = False
        await self._queue.join()
        if self._task:
            self._task.cancel()
        logger.info("Event bus stopped")

    async def _process(self) -> None:
        while self._running:
            try:
                event, data = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                handlers = self._subscribers.get(event, [])
                await asyncio.gather(*[h(data) for h in handlers], return_exceptions=True)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Event bus error: %s", e)


event_bus = EventBus()
