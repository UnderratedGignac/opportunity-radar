"""Base agent — extracted from auto-apply-agent's BaseAgent pattern."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Typed base for all Opportunity Radar agents."""

    name: str = "base"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"radar.agent.{self.name}")

    @abstractmethod
    async def run(self, payload: InputT) -> OutputT:
        ...

    def _log_start(self, detail: str = "") -> None:
        self.logger.info("[%s] starting — %s", self.name, detail)

    def _log_done(self, detail: str = "") -> None:
        self.logger.info("[%s] done — %s", self.name, detail)
