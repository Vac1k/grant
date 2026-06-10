from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from grant_tool.config import get_settings
from grant_tool.db.models import ApplicationHistory, ClientProfile, Grant, JobRun, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.utils import clean_text


EMBEDDING_DIMENSION = 1536
EMBEDDING_TEXT_VERSION = "stage7-profile-text-v1"


class EmbeddingTarget(StrEnum):
    GRANTS = "grants"
    CLIENTS = "clients"
    HISTORY = "history"
    ALL = "all"


@dataclass(slots=True)
class EmbeddingSummary:
    job: JobRun
    target: str
    processed_count: int
    updated_count: int
    failed_count: int
    errors: list[str]


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Deterministic local embedding provider for tests and offline smoke runs."""

    model = "local-hash-embedding-v1"

    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSION) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-zа-яіїєґ0-9]{2,}", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class OpenAIEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()["data"]
        ordered = sorted(data, key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]


class EmbeddingService:
    def __init__(
        self,
        *,
        repository: GrantRepository,
        provider: EmbeddingProvider | None = None,
        provider_name: str = "hash",
    ) -> None:
        self.repository = repository
        self.provider = provider or self._provider(provider_name)

    def run(
        self,
        *,
        target: EmbeddingTarget | str = EmbeddingTarget.ALL,
        limit: int | None = None,
        batch_size: int = 16,
    ) -> EmbeddingSummary:
        target_value = EmbeddingTarget(target).value
        job = self.repository.start_job(
            job_type=JobType.EMBEDDING,
            job_metadata={
                "target": target_value,
                "limit": limit,
                "batch_size": batch_size,
                "provider_model": self.provider.model,
                "embedding_text_version": EMBEDDING_TEXT_VERSION,
            },
        )
        errors: list[str] = []
        processed = 0
        updated = 0
        failed = 0

        records = self._records(target=EmbeddingTarget(target), limit=limit)
        try:
            for start in range(0, len(records), batch_size):
                batch = records[start : start + batch_size]
                texts = [self.profile_text(record) for record in batch]
                try:
                    vectors = self.provider.embed(texts)
                except Exception as exc:
                    failed += len(batch)
                    processed += len(batch)
                    errors.append(f"batch {start}: {exc}")
                    self.repository.increment_job_counters(job, processed=len(batch), failed=len(batch))
                    continue

                now = datetime.now(UTC)
                for record, text, vector in zip(batch, texts, vectors, strict=True):
                    record.embedding = vector
                    record.embedding_text = text
                    record.embedding_model = self.provider.model
                    record.embedded_at = now
                    processed += 1
                    updated += 1
                    self.repository.increment_job_counters(job, processed=1, updated=1)

            if errors:
                self.repository.mark_job_partial(job, error_message=f"{len(errors)} embedding errors", job_metadata={"errors": errors[:20]})
            else:
                self.repository.finish_job_success(job)
        except Exception as exc:
            self.repository.finish_job_failed(job, error_message=str(exc), job_metadata={"errors": errors[:20]})
            raise

        return EmbeddingSummary(
            job=job,
            target=target_value,
            processed_count=processed,
            updated_count=updated,
            failed_count=failed,
            errors=errors,
        )

    def _records(self, *, target: EmbeddingTarget, limit: int | None) -> list[Grant | ClientProfile | ApplicationHistory]:
        records: list[Grant | ClientProfile | ApplicationHistory] = []
        if target in {EmbeddingTarget.GRANTS, EmbeddingTarget.ALL}:
            records.extend(self.repository.list_grants_for_embedding(limit=limit))
        if target in {EmbeddingTarget.CLIENTS, EmbeddingTarget.ALL}:
            records.extend(self.repository.list_client_profiles_for_embedding(limit=limit))
        if target in {EmbeddingTarget.HISTORY, EmbeddingTarget.ALL}:
            records.extend(self.repository.list_application_history_for_embedding(limit=limit))
        return records

    @staticmethod
    def profile_text(record: Grant | ClientProfile | ApplicationHistory) -> str:
        if isinstance(record, Grant):
            return EmbeddingService.grant_profile_text(record)
        if isinstance(record, ClientProfile):
            return EmbeddingService.client_profile_text(record)
        return EmbeddingService.history_profile_text(record)

    @staticmethod
    def grant_profile_text(grant: Grant) -> str:
        parts = [
            f"Title: {grant.title}",
            f"Summary: {grant.summary}",
            f"Program: {grant.program_name}",
            f"Funder: {grant.funder_name}",
            f"Status: {grant.status}",
            f"Opportunity type: {grant.opportunity_type}",
            f"Support type: {grant.support_type}",
            f"Funding: {grant.funding_amount_text} {grant.currency or ''}",
            f"Countries: {', '.join(grant.countries or [])}",
            f"Applicant types: {', '.join(grant.applicant_types or [])}",
            f"Topics: {', '.join(grant.topics or [])}",
            f"Keywords: {', '.join(grant.keywords or [])}",
            f"Eligibility: {grant.eligibility_text}",
            f"Restrictions: {grant.restrictions_text}",
            f"Cofinancing: {grant.cofinancing_text}",
            f"Consortium: {grant.consortium_text}",
            f"Description: {grant.description_text}",
        ]
        return EmbeddingService._compact(parts)

    @staticmethod
    def client_profile_text(client: ClientProfile) -> str:
        parts = [
            f"Client: {client.name}",
            f"Country: {client.country}",
            f"Sector: {client.sector}",
            f"Organization type: {client.organization_type}",
            f"Technologies: {', '.join(client.technologies or [])}",
            f"Target topics: {', '.join(client.target_topics or [])}",
            f"Excluded topics: {', '.join(client.excluded_topics or [])}",
            f"Product: {client.product_description}",
            f"Risks: {client.risks}",
            f"Previous submissions: {client.previous_submissions_summary}",
        ]
        return EmbeddingService._compact(parts)

    @staticmethod
    def history_profile_text(history: ApplicationHistory) -> str:
        parts = [
            f"Client: {history.client_name}",
            f"Grant title: {history.grant_title}",
            f"Grant source: {history.grant_source}",
            f"Program: {history.program_name}",
            f"Result: {history.result}",
            f"Country: {history.country}",
            f"Applicant type: {history.applicant_type}",
            f"Topics: {', '.join(history.topics or [])}",
            f"Project summary: {history.project_summary}",
            f"Reusable materials: {history.reusable_materials}",
            f"Notes: {history.notes}",
        ]
        return EmbeddingService._compact(parts)

    @staticmethod
    def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float | None:
        if not left or not right or len(left) != len(right):
            return None
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return None
        return dot / (left_norm * right_norm)

    @staticmethod
    def _compact(parts: list[str]) -> str:
        text = "\n".join(part for part in parts if part and not part.endswith(": None"))
        return clean_text(text)[:12000] or ""

    @staticmethod
    def _provider(provider_name: str) -> EmbeddingProvider:
        if provider_name == "hash":
            return HashEmbeddingProvider()
        if provider_name == "openai":
            settings = get_settings()
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
            return OpenAIEmbeddingProvider(api_key=settings.openai_api_key, model=settings.embedding_model)
        raise ValueError(f"Unsupported embedding provider: {provider_name}")
