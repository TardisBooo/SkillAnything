"""Connector selection."""

from __future__ import annotations

from skillanything.config import Settings
from skillanything.connectors.base import Connector, ConnectorError, FetchRequest
from skillanything.connectors.file import FileConnector
from skillanything.connectors.rsshub import RSSHubConnector
from skillanything.connectors.web import WebConnector
from skillanything.connectors.x import XConnector
from skillanything.connectors.xiaohongshu import XiaohongshuConnector
from skillanything.connectors.xueqiu import XueqiuConnector


def connector_chain(settings: Settings) -> list[Connector]:
    return [
        FileConnector(),
        XConnector(settings),
        XiaohongshuConnector(settings),
        XueqiuConnector(settings),
        RSSHubConnector(settings),
        WebConnector(),
    ]


def build_connector(settings: Settings, request: FetchRequest) -> Connector:
    for connector in connector_chain(settings):
        if connector.can_handle(request):
            return connector
    raise ConnectorError(f"no connector can handle source: {request.source}")
