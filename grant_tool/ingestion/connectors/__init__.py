from grant_tool.ingestion.connectors.diia_business import DiiaBusinessConnector
from grant_tool.ingestion.connectors.eu_funding import EUFundingConnector
from grant_tool.ingestion.connectors.gurt import GurtConnector
from grant_tool.ingestion.connectors.prostir import ProstirConnector

CONNECTOR_CLASSES = {
    EUFundingConnector.source_slug: EUFundingConnector,
    ProstirConnector.source_slug: ProstirConnector,
    DiiaBusinessConnector.source_slug: DiiaBusinessConnector,
    GurtConnector.source_slug: GurtConnector,
}

__all__ = [
    "CONNECTOR_CLASSES",
    "DiiaBusinessConnector",
    "EUFundingConnector",
    "GurtConnector",
    "ProstirConnector",
]
