from __future__ import annotations

import unittest

from grant_tool.data_quality import (
    NORMALIZATION_RULE_VERSION,
    clean_funding_amount_text,
    normalize_currency,
    normalize_grant_draft,
    normalize_support_type,
)
from grant_tool.ingestion.types import NormalizedGrantDraft


class DataNormalizationTestCase(unittest.TestCase):
    def test_currency_aliases_are_normalized_without_cad_usd_collision(self) -> None:
        self.assertEqual(normalize_currency("20 000 GBP"), "GBP")
        self.assertEqual(normalize_currency("C$ 25,000"), "CAD")
        self.assertEqual(normalize_currency("до 500 000 грн"), "UAH")

    def test_funding_amount_text_cleanup_removes_noise_not_value(self) -> None:
        self.assertEqual(clean_funding_amount_text("Сума: до 20 000 фунтів"), "до 20 000 фунтів")
        self.assertIsNone(
            clean_funding_amount_text('{"budgetTopicActionMap":{"167264":[{"deadlineDates":["2026-03-19"]}]}}')
        )
        self.assertIsNone(clean_funding_amount_text("EUR 2026"))

    def test_normalize_grant_draft_fills_critical_fields(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://chaszmin.com.ua/granty-acted/",
            title="До 20 000 фунтів - гранти для ГО (ACTED)",
            status="active",
            deadline_text="Актуально до: 25.12.26 Зафіксувати у Google календарі",
            description_text="Грант для громадських організацій у Харківській області, Україна.",
            funding_amount_text="Сума: до 20 000 фунтів",
            support_type="грант",
            eligibility_text="До участі допускаються ГО. Поділитися",
        )
        fields: dict[str, object] = {}

        result = normalize_grant_draft(
            draft,
            source_slug="chas-zmin",
            text=draft.description_text or "",
            fields=fields,
        )

        self.assertEqual(draft.status, "open")
        self.assertEqual(draft.deadline_at.date().isoformat(), "2026-12-25")
        self.assertEqual(draft.deadline_text, "Актуально до: 25.12.26")
        self.assertEqual(draft.currency, "GBP")
        self.assertEqual(draft.funding_amount_text, "до 20 000 фунтів")
        self.assertEqual(draft.funder_name, "ACTED")
        self.assertIn("Ukraine", draft.countries)
        self.assertIn("Kharkiv", draft.regions)
        self.assertEqual(draft.support_type, "grant")
        self.assertEqual(draft.opportunity_type, "grant")
        self.assertEqual(draft.eligibility_text, "До участі допускаються ГО.")
        self.assertIn("deadline_at", result.changed_fields)
        self.assertEqual(draft.extraction_metadata["normalization_rule_version"], NORMALIZATION_RULE_VERSION)
        self.assertIn("normalized_fields", draft.extraction_metadata)
        self.assertIn("currency_normalized", fields)

    def test_support_type_inference_maps_business_finance_to_business_support(self) -> None:
        self.assertEqual(normalize_support_type(None, text="Пільговий кредит для бізнесу"), "loan")

        draft = NormalizedGrantDraft(
            source_url="https://example.org/loan",
            title="Пільговий кредит для малого бізнесу",
            description_text="Фінансова підтримка підприємців.",
        )

        normalize_grant_draft(draft, source_slug="example", text=draft.description_text or "", fields={})

        self.assertEqual(draft.support_type, "loan")
        self.assertEqual(draft.opportunity_type, "business_support")

    def test_uncertain_amount_currency_adds_review_reason_without_dropping_raw_text(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://example.org/amount",
            title="Грант для громад",
            funding_amount_text="до 50000",
        )

        result = normalize_grant_draft(draft, source_slug="example", text="", fields={})

        self.assertEqual(draft.funding_amount_text, "до 50000")
        self.assertEqual(result.review_reasons, ("funding amount has no reliable currency",))

    def test_source_level_funder_fallback_is_applied(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/TEST",
            title="EU innovation grant",
        )

        normalize_grant_draft(draft, source_slug="eu-funding", text="", fields={})

        self.assertEqual(draft.funder_name, "European Commission")


if __name__ == "__main__":
    unittest.main()
