from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from grant_tool.config import get_settings
from grant_tool.db.models import ApplicationHistory, Grant, GrantClientMatch, JobRun, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.embeddings import EmbeddingService
from grant_tool.ingestion.utils import clean_text


EXPLANATION_VERSION = "stage8-llm-explanation-v1"


@dataclass(slots=True)
class ExplanationSummary:
    job: JobRun
    match_run_id: uuid.UUID
    processed_count: int
    updated_count: int
    failed_count: int
    errors: list[str]


class ExplanationClient(Protocol):
    model: str

    def explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class RuleBasedExplanationClient:
    """Deterministic fallback for tests/offline usage."""

    model = "local-rule-explanation-v1"

    def explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        match = payload.get("match", {})
        score = match.get("score_breakdown", {})
        evidence = match.get("evidence", {})
        keyword = evidence.get("keyword", {})
        vector = evidence.get("vector", {})
        history = evidence.get("history", {})
        manual_checks = list(match.get("manual_checks") or [])

        reasons: list[str] = []
        topic_hits = keyword.get("topic_hits") or []
        technology_hits = keyword.get("technology_hits") or []
        if topic_hits:
            reasons.append("topic overlap: " + ", ".join(topic_hits))
        if technology_hits:
            reasons.append("technology overlap: " + ", ".join(technology_hits))
        if vector.get("grant_client_similarity"):
            reasons.append(f"semantic similarity {vector['grant_client_similarity']}")
        if history.get("matched_history"):
            reasons.append("similar previous application history")
        if not reasons:
            reasons.append("match passed deterministic shortlist filters")

        risks: list[str] = []
        if Decimal(str(score.get("final_score") or "0")) < Decimal("0.3000"):
            risks.append("Low overall score; review fit before prioritising.")
        if manual_checks:
            risks.append("Some fields need manual verification.")

        return {
            "explanation": "Candidate match because " + "; ".join(reasons) + ".",
            "risks_text": " ".join(risks) or "No major deterministic risks detected.",
            "manual_checks": manual_checks,
            "llm_score": score.get("final_score"),
            "confidence": "0.6000",
        }


class OpenAIExplanationClient:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        system_prompt = (
            "You explain grant-client match results for a grant management tool. "
            "Do not decide whether this is a match from scratch. Use only the provided score breakdown, "
            "grant profile, client profile, application history, evidence, and manual checks. "
            "Lost, rejected, or not_submitted history is not negative fit evidence. "
            "Return compact JSON with keys: explanation, risks_text, manual_checks, llm_score, confidence. "
            "manual_checks must be an array of short practical checks. "
            "llm_score must be a number between 0 and 1 reflecting explanation confidence, not a replacement for final_score."
        )
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


class MatchExplanationService:
    def __init__(
        self,
        *,
        repository: GrantRepository,
        client: ExplanationClient | None = None,
        provider: str = "rule",
    ) -> None:
        self.repository = repository
        self.client = client or self._client(provider)

    def run(
        self,
        *,
        match_run_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> ExplanationSummary:
        match_run = self.repository.get_match_run(match_run_id) if match_run_id else self.repository.latest_match_run()
        if match_run is None:
            raise ValueError("No match run found for explanation generation")

        job = self.repository.start_job(
            job_type=JobType.LLM_EXTRACTION,
            job_metadata={
                "stage": "stage_8",
                "match_run_id": str(match_run.id),
                "limit": limit,
                "provider_model": self.client.model,
                "explanation_version": EXPLANATION_VERSION,
            },
        )
        matches = self.repository.list_matches_for_explanation(match_run_id=match_run.id, limit=limit)
        errors: list[str] = []
        processed = 0
        updated = 0
        failed = 0

        try:
            for match in matches:
                processed += 1
                try:
                    payload = self._payload(match)
                    result = self.client.explain(payload)
                    self._apply_result(match, result)
                    updated += 1
                    self.repository.increment_job_counters(job, processed=1, updated=1)
                except Exception as exc:
                    failed += 1
                    errors.append(f"{match.id}: {exc}")
                    self.repository.increment_job_counters(job, processed=1, failed=1)

            if errors:
                self.repository.mark_job_partial(
                    job,
                    error_message=f"{len(errors)} explanation errors",
                    job_metadata={"errors": errors[:20]},
                )
            else:
                self.repository.finish_job_success(job)
        except Exception as exc:
            self.repository.finish_job_failed(job, error_message=str(exc), job_metadata={"errors": errors[:20]})
            raise

        return ExplanationSummary(
            job=job,
            match_run_id=match_run.id,
            processed_count=processed,
            updated_count=updated,
            failed_count=failed,
            errors=errors,
        )

    def _payload(self, match: GrantClientMatch) -> dict[str, Any]:
        grant = match.grant
        client = match.client_profile
        history = self.repository.list_application_history_for_client(client.id)
        return {
            "instruction": "Explain existing match evidence. Do not override deterministic/vector scores.",
            "match": {
                "score": str(match.score),
                "rank": match.rank,
                "score_breakdown": (match.match_metadata or {}).get("score_breakdown", {}),
                "manual_checks": match.manual_checks or [],
                "evidence": match.evidence or {},
            },
            "grant_profile": self._grant_profile(grant),
            "client_profile": self._client_profile(client),
            "relevant_application_history": self._history_profiles(history, match),
        }

    @staticmethod
    def _grant_profile(grant: Grant) -> dict[str, Any]:
        feature_card = (grant.extraction_metadata or {}).get("feature_card", {})
        return {
            "title": grant.title,
            "source": grant.source.slug if grant.source else None,
            "source_url": grant.source_url,
            "summary": grant.summary,
            "status": grant.status,
            "deadline_text": grant.deadline_text,
            "funding": grant.funding_amount_text,
            "currency": grant.currency,
            "countries": grant.countries,
            "applicant_types": grant.applicant_types,
            "topics": grant.topics,
            "eligibility_text": grant.eligibility_text,
            "restrictions_text": grant.restrictions_text,
            "support_type": grant.support_type,
            "opportunity_type": grant.opportunity_type,
            "feature_card": feature_card,
            "profile_text": grant.embedding_text or EmbeddingService.grant_profile_text(grant),
        }

    @staticmethod
    def _client_profile(client: Any) -> dict[str, Any]:
        return {
            "name": client.name,
            "slug": client.slug,
            "country": client.country,
            "sector": client.sector,
            "organization_type": client.organization_type,
            "technologies": client.technologies,
            "target_topics": client.target_topics,
            "excluded_topics": client.excluded_topics,
            "product_description": client.product_description,
            "risks": client.risks,
            "profile_text": client.embedding_text or EmbeddingService.client_profile_text(client),
        }

    @staticmethod
    def _history_profiles(history: list[ApplicationHistory], match: GrantClientMatch) -> list[dict[str, Any]]:
        evidence_titles: set[str] = set()
        for item in ((match.evidence or {}).get("history", {}).get("matched_history") or []):
            if not isinstance(item, dict):
                continue
            title = clean_text(item.get("grant_title"))
            if title:
                evidence_titles.add(title.lower())

        selected = []
        for item in history:
            history_title = clean_text(item.grant_title)
            if evidence_titles and (not history_title or history_title.lower() not in evidence_titles):
                continue
            selected.append(
                {
                    "grant_title": item.grant_title,
                    "grant_source": item.grant_source,
                    "program_name": item.program_name,
                    "result": item.result,
                    "topics": item.topics,
                    "project_summary": item.project_summary,
                    "reusable_materials": item.reusable_materials,
                    "similarity_weight": str(item.similarity_weight),
                    "profile_text": item.embedding_text or EmbeddingService.history_profile_text(item),
                }
            )
            if len(selected) >= 5:
                break
        return selected

    def _apply_result(self, match: GrantClientMatch, result: dict[str, Any]) -> None:
        explanation = clean_text(result.get("explanation"))
        risks_text = clean_text(result.get("risks_text"))
        manual_checks = result.get("manual_checks")
        llm_score = self._decimal_or_none(result.get("llm_score"))
        confidence = self._decimal_or_none(result.get("confidence"))

        if explanation:
            match.explanation = explanation
        if risks_text:
            match.risks_text = risks_text
        if isinstance(manual_checks, list):
            match.manual_checks = self._merge_checks(match.manual_checks or [], [clean_text(str(item)) for item in manual_checks])
        if llm_score is not None:
            match.llm_score = llm_score

        metadata = dict(match.match_metadata or {})
        metadata["llm_explanation"] = {
            "version": EXPLANATION_VERSION,
            "provider_model": self.client.model,
            "generated_at": datetime.now(UTC).isoformat(),
            "confidence": str(confidence) if confidence is not None else None,
        }
        match.match_metadata = metadata
        self.repository.session.flush()

    @staticmethod
    def _merge_checks(existing: list[str], additions: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in [*existing, *additions]:
            cleaned = clean_text(item)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value)).quantize(Decimal("0.0001"))
        except Exception:
            return None

    @staticmethod
    def _client(provider: str) -> ExplanationClient:
        if provider == "rule":
            return RuleBasedExplanationClient()
        if provider == "openai":
            settings = get_settings()
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required for OpenAI explanations")
            return OpenAIExplanationClient(api_key=settings.openai_api_key, model=settings.llm_model)
        raise ValueError(f"Unsupported explanation provider: {provider}")
