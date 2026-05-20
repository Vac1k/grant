from __future__ import annotations

from abc import ABC, abstractmethod

from grant_tool.db.models import Source
from grant_tool.ingestion.http import HttpClient
from grant_tool.ingestion.types import ConnectorResult


class BaseConnector(ABC):
    source_slug: str

    def __init__(self, *, source: Source, http_client: HttpClient) -> None:
        self.source = source
        self.http = http_client

    @abstractmethod
    def run(self, *, limit: int) -> ConnectorResult:
        raise NotImplementedError
