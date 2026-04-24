import unittest

from app.services.transcription.models import TranscriptSegment, TranscriptWord
from app.services.transcription.stitcher import TranscriptStitcher


class TranscriptStitcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stitcher = TranscriptStitcher()

    def test_overlap_words_are_trimmed_to_unique_chunk_region(self) -> None:
        chunk_rows = [
            {
                "id": 1,
                "start_ms": 0,
                "end_ms": 60_000,
                "overlap_before_ms": 0,
                "overlap_after_ms": 1_500,
            },
            {
                "id": 2,
                "start_ms": 58_500,
                "end_ms": 120_000,
                "overlap_before_ms": 1_500,
                "overlap_after_ms": 0,
            },
        ]
        chunk_segment_map = {
            1: [
                TranscriptSegment(
                    text="alpha beta",
                    start_ms_in_chunk=58_000,
                    end_ms_in_chunk=58_900,
                    speaker_label="speaker_1",
                    confidence=0.9,
                    words=[
                        TranscriptWord("alpha", 58_000, 58_400, "speaker_1", 0.9),
                        TranscriptWord("beta", 58_500, 58_900, "speaker_1", 0.9),
                    ],
                )
            ],
            2: [
                TranscriptSegment(
                    text="alpha beta gamma",
                    start_ms_in_chunk=0,
                    end_ms_in_chunk=3_000,
                    speaker_label="speaker_1",
                    confidence=0.9,
                    words=[
                        TranscriptWord("alpha", 0, 400, "speaker_1", 0.9),
                        TranscriptWord("beta", 500, 900, "speaker_1", 0.9),
                        TranscriptWord("gamma", 2_000, 2_400, "speaker_1", 0.9),
                    ],
                )
            ],
        }

        stitched = self.stitcher.stitch(
            meeting_id=99,
            transcription_run_id=7,
            chunk_rows=chunk_rows,
            chunk_segment_map=chunk_segment_map,
        )

        merged_text = " ".join(segment["text"] for segment in stitched["merged_segments"])
        self.assertEqual(merged_text, "alpha beta gamma")
        self.assertEqual(stitched["report"]["dropped_word_count"], 0)
        self.assertEqual(stitched["merged_segments"][0]["start_ms_in_meeting"], 58_000)
        self.assertEqual(len(stitched["merged_segments"]), 2)
        self.assertEqual(stitched["merged_segments"][0]["end_ms_in_meeting"], 58_900)
        self.assertEqual(stitched["merged_segments"][1]["start_ms_in_meeting"], 60_500)


if __name__ == "__main__":
    unittest.main()
