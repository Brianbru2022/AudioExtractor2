from __future__ import annotations

from app.models.domain import PlannedChunk


class ChunkPlanningService:
    def plan(
        self,
        *,
        duration_ms: int,
        silence_candidates: list[dict[str, int]],
        target_ms: int,
        hard_max_ms: int,
        min_chunk_ms: int,
        overlap_ms: int,
    ) -> dict[str, object]:
        base_start = 0
        chunk_index = 0
        base_chunks: list[dict[str, int | str]] = []
        sorted_candidates = self._prepare_candidates(silence_candidates)

        while duration_ms - base_start > hard_max_ms:
            soft_target = base_start + target_ms
            min_boundary = base_start + min_chunk_ms
            hard_boundary = min(base_start + hard_max_ms, duration_ms)

            valid_candidates = [
                candidate
                for candidate in sorted_candidates
                if min_boundary <= candidate["boundary_ms"] <= hard_boundary
            ]

            if valid_candidates:
                chosen = self._choose_candidate(valid_candidates, soft_target)
                boundary_ms = int(chosen["chosen_boundary_ms"])
                boundary_reason = "silence_preferred"
            else:
                boundary_ms = hard_boundary
                boundary_reason = "hard_max_fallback"

            base_chunks.append(
                {
                    "chunk_index": chunk_index,
                    "base_start_ms": base_start,
                    "base_end_ms": boundary_ms,
                    "boundary_reason": boundary_reason,
                }
            )
            chunk_index += 1
            base_start = boundary_ms

        if base_chunks and duration_ms - base_start < min_chunk_ms:
            previous = base_chunks[-1]
            base_chunks[-1] = {
                "chunk_index": previous["chunk_index"],
                "base_start_ms": previous["base_start_ms"],
                "base_end_ms": duration_ms,
                "boundary_reason": "min_length_adjustment",
            }
        else:
            base_chunks.append(
                {
                    "chunk_index": chunk_index,
                    "base_start_ms": base_start,
                    "base_end_ms": duration_ms,
                    "boundary_reason": "final_tail",
                }
            )

        chunks = self._build_chunks(
            base_chunks=base_chunks,
            duration_ms=duration_ms,
            overlap_ms=overlap_ms,
        )
        validation = self._validate_chunks(chunks, duration_ms, overlap_ms)

        return {
            "strategy": {
                "target_ms": target_ms,
                "hard_max_ms": hard_max_ms,
                "min_chunk_ms": min_chunk_ms,
                "overlap_ms": overlap_ms,
                "candidate_count": len(sorted_candidates),
                "coverage_validation": validation,
            },
            "chunks": [chunk.__dict__ for chunk in chunks],
        }

    def _build_chunks(
        self,
        *,
        base_chunks: list[dict[str, int | str]],
        duration_ms: int,
        overlap_ms: int,
    ) -> list[PlannedChunk]:
        chunks: list[PlannedChunk] = []
        before_overlap = overlap_ms // 2
        after_overlap = overlap_ms - before_overlap

        for index, base_chunk in enumerate(base_chunks):
            is_first = index == 0
            is_last = index == len(base_chunks) - 1
            overlap_before = 0 if is_first else before_overlap
            overlap_after = 0 if is_last else after_overlap
            start_ms = max(0, int(base_chunk["base_start_ms"]) - overlap_before)
            end_ms = min(duration_ms, int(base_chunk["base_end_ms"]) + overlap_after)
            chunks.append(
                PlannedChunk(
                    chunk_index=int(base_chunk["chunk_index"]),
                    base_start_ms=int(base_chunk["base_start_ms"]),
                    base_end_ms=int(base_chunk["base_end_ms"]),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    overlap_before_ms=overlap_before,
                    overlap_after_ms=overlap_after,
                    duration_ms=end_ms - start_ms,
                    boundary_reason=str(base_chunk["boundary_reason"]),
                )
            )

        return chunks

    @staticmethod
    def _prepare_candidates(candidates: list[dict[str, int]]) -> list[dict[str, int]]:
        seen: set[int] = set()
        normalized: list[dict[str, int]] = []
        for candidate in sorted(candidates, key=lambda item: (item["boundary_ms"], item.get("duration_ms", 0))):
            boundary_ms = int(candidate["boundary_ms"])
            if boundary_ms in seen:
                continue
            seen.add(boundary_ms)
            normalized.append(
                {
                    "start_ms": int(candidate.get("start_ms", boundary_ms)),
                    "end_ms": int(candidate.get("end_ms", boundary_ms)),
                    "duration_ms": int(candidate.get("duration_ms", 0)),
                    "boundary_ms": boundary_ms,
                }
            )
        return normalized

    @staticmethod
    def _choose_candidate(candidates: list[dict[str, int]], soft_target: int) -> dict[str, int]:
        best: dict[str, int] | None = None
        best_score: tuple[int, int, int] | None = None

        for candidate in candidates:
            start_ms = candidate["start_ms"]
            end_ms = candidate["end_ms"]
            if start_ms <= soft_target <= end_ms:
                chosen_boundary_ms = soft_target
            else:
                chosen_boundary_ms = candidate["boundary_ms"]

            score = (
                abs(chosen_boundary_ms - soft_target),
                abs(candidate["boundary_ms"] - soft_target),
                -candidate["duration_ms"],
            )
            if best_score is None or score < best_score:
                best_score = score
                best = {
                    **candidate,
                    "chosen_boundary_ms": chosen_boundary_ms,
                }

        return best or {
            "start_ms": soft_target,
            "end_ms": soft_target,
            "duration_ms": 0,
            "boundary_ms": soft_target,
            "chosen_boundary_ms": soft_target,
        }

    @staticmethod
    def _validate_chunks(chunks: list[PlannedChunk], duration_ms: int, overlap_ms: int) -> dict[str, int | bool]:
        gaps_ms = 0
        duplicate_beyond_overlap_ms = 0
        expected_next_base = 0

        for index, chunk in enumerate(chunks):
            if chunk.base_start_ms > expected_next_base:
                gaps_ms += chunk.base_start_ms - expected_next_base

            if chunk.base_start_ms < expected_next_base:
                duplicate_beyond_overlap_ms += expected_next_base - chunk.base_start_ms

            expected_next_base = chunk.base_end_ms

            if index > 0:
                previous = chunks[index - 1]
                actual_overlap_ms = previous.end_ms - chunk.start_ms
                extra_overlap_ms = max(0, actual_overlap_ms - overlap_ms)
                duplicate_beyond_overlap_ms += extra_overlap_ms

        return {
            "covers_full_duration": expected_next_base == duration_ms,
            "gaps_ms": gaps_ms,
            "duplicate_beyond_overlap_ms": duplicate_beyond_overlap_ms,
            "chunk_count": len(chunks),
            "intended_overlap_ms": overlap_ms,
        }
