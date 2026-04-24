import unittest

from app.services.extraction.context_selection import ExtractionContextSelector


class ExtractionContextSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selector = ExtractionContextSelector()

    def test_retrieval_context_selection_preserves_segment_traceability(self) -> None:
        segments = []
        segment_id = 1
        for topic_index in range(3):
            for segment_index in range(36):
                start_ms = (segment_id - 1) * 8_000
                topic = ["roadmap", "budget", "staffing"][topic_index]
                text = f"{topic} discussion item {segment_index}."
                if segment_index in {4, 18}:
                    text += " We need an owner for the next step."
                if segment_index in {11, 25}:
                    text += " Can we still hit the target date?"
                if segment_index in {15, 31}:
                    text += " The main risk is timeline slippage."
                segments.append(
                    {
                        "id": segment_id,
                        "text": text,
                        "speaker_label": f"speaker_{(segment_index % 2) + 1}",
                        "start_ms_in_meeting": start_ms,
                        "end_ms_in_meeting": start_ms + 7_000,
                    }
                )
                segment_id += 1

        windows, report = self.selector.select(segments, max_segments_per_window=24)
        selected_ids = [segment["id"] for window in windows for segment in window]

        self.assertEqual(report["mode"], "retrieval_context_selection")
        self.assertGreater(len(windows), 0)
        self.assertGreater(len(selected_ids), 40)
        self.assertTrue(set(selected_ids).issubset({segment["id"] for segment in segments}))
        self.assertIn(5, selected_ids)
        self.assertIn(16, selected_ids)
        self.assertIn(26, selected_ids)
        self.assertGreaterEqual(len(report["windows"]), 2)

    def test_context_selection_falls_back_to_single_window_for_small_transcripts(self) -> None:
        segments = [
            {
                "id": 1,
                "text": "We agreed to proceed.",
                "speaker_label": "speaker_1",
                "start_ms_in_meeting": 0,
                "end_ms_in_meeting": 8_000,
            },
            {
                "id": 2,
                "text": "Please send the updated deck.",
                "speaker_label": "speaker_2",
                "start_ms_in_meeting": 8_500,
                "end_ms_in_meeting": 16_000,
            },
        ]
        windows, report = self.selector.select(segments, max_segments_per_window=10)
        self.assertEqual(report["mode"], "single_window")
        self.assertEqual(len(windows), 1)
        self.assertEqual([segment["id"] for segment in windows[0]], [1, 2])


if __name__ == "__main__":
    unittest.main()
