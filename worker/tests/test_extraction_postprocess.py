import unittest

from app.services.extraction.postprocess import assess_review, dedupe_validated_entities, normalize_due_date, normalize_owner


class ExtractionPostprocessTests(unittest.TestCase):
    def test_duplicate_actions_collapse_by_intent_and_owner(self) -> None:
        items = [
            {
                "text": "Draft the revised launch plan before the board review.",
                "owner": "PM",
                "due_date": None,
                "priority": "high",
                "confidence": 0.78,
                "explicit_or_inferred": "inferred",
                "review_status": "pending",
                "evidence": [
                    {
                        "transcript_segment_id": 1,
                        "start_ms": 0,
                        "end_ms": 10_000,
                        "speaker_label": "speaker_1",
                        "quote_snippet": "We need the revised launch plan before the board review.",
                        "confidence": 0.78,
                    }
                ],
            },
            {
                "text": "Draft revised launch plan before board review",
                "owner": "PM",
                "due_date": None,
                "priority": "high",
                "confidence": 0.81,
                "explicit_or_inferred": "explicit",
                "review_status": "pending",
                "evidence": [
                    {
                        "transcript_segment_id": 2,
                        "start_ms": 11_000,
                        "end_ms": 18_000,
                        "speaker_label": "speaker_2",
                        "quote_snippet": "Please draft revised launch plan before board review.",
                        "confidence": 0.81,
                    }
                ],
            },
        ]
        deduped = dedupe_validated_entities("action_items", items, max_evidence_items=5)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["explicit_or_inferred"], "explicit")
        self.assertEqual(len(deduped[0]["evidence"]), 2)

    def test_owner_and_due_date_require_evidence_support(self) -> None:
        evidence_texts = ["We need the revised launch plan before the board review."]
        self.assertIsNone(normalize_owner("Alex", evidence_texts))
        self.assertIsNone(normalize_due_date("Friday", evidence_texts))
        self.assertEqual(normalize_owner("board review", evidence_texts), "board review")

    def test_review_assessment_flags_pending_and_low_confidence_items(self) -> None:
        assessment = assess_review(
            {
                "review_status": "pending",
                "confidence": 0.55,
                "explicit_or_inferred": "inferred",
                "evidence": [{"id": 1}],
                "owner": None,
                "due_date": None,
            },
            low_confidence_threshold=0.7,
        )
        self.assertTrue(assessment.needs_review)
        self.assertGreaterEqual(len(assessment.review_hints), 4)


if __name__ == "__main__":
    unittest.main()
