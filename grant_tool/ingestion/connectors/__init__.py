from grant_tool.ingestion.connectors.diia_business import DiiaBusinessConnector
from grant_tool.ingestion.connectors.eu_funding import EUFundingConnector
from grant_tool.ingestion.connectors.gurt import GurtConnector
from grant_tool.ingestion.connectors.prostir import ProstirConnector
from grant_tool.ingestion.connectors.wordpress import ChasZminConnector, EUFundingPortalEuConnector, HromadyConnector

CONNECTOR_CLASSES = {
    EUFundingConnector.source_slug: EUFundingConnector,
    ProstirConnector.source_slug: ProstirConnector,
    DiiaBusinessConnector.source_slug: DiiaBusinessConnector,
    GurtConnector.source_slug: GurtConnector,
    ChasZminConnector.source_slug: ChasZminConnector,
    EUFundingPortalEuConnector.source_slug: EUFundingPortalEuConnector,
    HromadyConnector.source_slug: HromadyConnector,
}

__all__ = [
    "ChasZminConnector",
    "CONNECTOR_CLASSES",
    "DiiaBusinessConnector",
    "EUFundingPortalEuConnector",
    "EUFundingConnector",
    "GurtConnector",
    "HromadyConnector",
    "ProstirConnector",
]
