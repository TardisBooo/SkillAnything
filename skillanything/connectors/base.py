"""Connector contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from skillanything.models import CollectResult


class ConnectorError(RuntimeError):
    """Raised when a connector cannot fetch or parse a source."""


@dataclass(frozen=True, slots=True)
class FetchRequest:
    source: str
    platform: str | None = None
    max_items: int = 50
    include_comments: bool = False
    include_media: bool = True
    deep: bool = True


class Connector(ABC):
    name: str

    @abstractmethod
    def can_handle(self, request: FetchRequest) -> bool:
        raise NotImplementedError

    @abstractmethod
    def collect(self, request: FetchRequest) -> CollectResult:
        raise NotImplementedError
