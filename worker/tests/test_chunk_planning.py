import unittest

from app.services.chunk_planning.service import ChunkPlanningService


class ChunkPlanningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = ChunkPlanningService()

    def test_chunk_planning_prefers_silence_candidates(self) -> None:
        plan = self.planner.plan(
            duration_ms=1_500_000,
            silence_candidates=[
                {"start_ms": 597_600, "end_ms": 598_400, "duration_ms": 800, "boundary_ms": 598_000},
                {"start_ms": 1_204_200, "end_ms": 1_205_800, "duration_ms": 1_600, "boundary_ms": 1_205_000},
            ],
            target_ms=600_000,
            hard_max_ms=720_000,
            min_chunk_ms=180_000,
            overlap_ms=1_500,
        )

        self.assertEqual(len(plan["chunks"]), 3)
        self.assertEqual(plan["chunks"][0]["boundary_reason"], "silence_preferred")
        self.assertEqual(plan["chunks"][0]["base_end_ms"], 598_000)
        self.assertTrue(plan["strategy"]["coverage_validation"]["covers_full_duration"])
        self.assertEqual(plan["strategy"]["coverage_validation"]["gaps_ms"], 0)
        self.assertEqual(plan["strategy"]["coverage_validation"]["duplicate_beyond_overlap_ms"], 0)

    def test_chunk_planning_handles_sparse_candidates(self) -> None:
        plan = self.planner.plan(
            duration_ms=7_200_000,
            silence_candidates=[],
            target_ms=600_000,
            hard_max_ms=720_000,
            min_chunk_ms=180_000,
            overlap_ms=1_500,
        )

        self.assertEqual(len(plan["chunks"]), 10)
        self.assertTrue(all(chunk["boundary_reason"] in {"hard_max_fallback", "final_tail"} for chunk in plan["chunks"]))
        self.assertEqual(plan["strategy"]["coverage_validation"]["gaps_ms"], 0)
        self.assertEqual(plan["strategy"]["coverage_validation"]["duplicate_beyond_overlap_ms"], 0)

    def test_chunk_planning_handles_long_silence_stretch(self) -> None:
        plan = self.planner.plan(
            duration_ms=900_000,
            silence_candidates=[
                {"start_ms": 595_000, "end_ms": 630_000, "duration_ms": 35_000, "boundary_ms": 612_500},
            ],
            target_ms=600_000,
            hard_max_ms=720_000,
            min_chunk_ms=180_000,
            overlap_ms=1_500,
        )

        self.assertEqual(plan["chunks"][0]["base_end_ms"], 600_000)
        self.assertEqual(plan["chunks"][0]["boundary_reason"], "silence_preferred")

    def test_chunk_planning_three_hour_coverage_is_stable(self) -> None:
        candidates = []
        for minute in range(10, 180, 10):
            boundary_ms = minute * 60_000 + 500
            candidates.append(
                {
                    "start_ms": boundary_ms - 400,
                    "end_ms": boundary_ms + 400,
                    "duration_ms": 800,
                    "boundary_ms": boundary_ms,
                }
            )

        plan = self.planner.plan(
            duration_ms=10_800_000,
            silence_candidates=candidates,
            target_ms=600_000,
            hard_max_ms=720_000,
            min_chunk_ms=180_000,
            overlap_ms=1_500,
        )

        validation = plan["strategy"]["coverage_validation"]
        self.assertGreaterEqual(validation["chunk_count"], 15)
        self.assertTrue(validation["covers_full_duration"])
        self.assertEqual(validation["gaps_ms"], 0)
        self.assertEqual(validation["duplicate_beyond_overlap_ms"], 0)


if __name__ == "__main__":
    unittest.main()
