from __future__ import annotations

from typing import Any

from app.services.transcription.models import TranscriptSegment


class TranscriptStitcher:
    def stitch(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        chunk_rows: list[dict[str, Any]],
        chunk_segment_map: dict[int, list[TranscriptSegment]],
    ) -> dict[str, Any]:
        merged_segments: list[dict[str, Any]] = []
        raw_segments: list[dict[str, Any]] = []
        raw_words: list[dict[str, Any]] = []
        raw_segment_index = 0
        raw_word_index = 0
        dropped_segments = 0
        dropped_words = 0

        for chunk in chunk_rows:
            chunk_id = int(chunk["id"])
            chunk_start_ms = int(chunk["start_ms"])
            unique_start_ms = chunk_start_ms + int(chunk["overlap_before_ms"])
            unique_end_ms = int(chunk["end_ms"]) - int(chunk["overlap_after_ms"])
            for segment in chunk_segment_map.get(chunk_id, []):
                raw_segments.append(
                    _segment_row(
                        meeting_id=meeting_id,
                        transcription_run_id=transcription_run_id,
                        chunk_id=chunk_id,
                        segment_index=raw_segment_index,
                        text=segment.text,
                        speaker_label=segment.speaker_label,
                        confidence=segment.confidence,
                        start_ms_in_meeting=_meeting_time(chunk_start_ms, segment.start_ms_in_chunk),
                        end_ms_in_meeting=_meeting_time(chunk_start_ms, segment.end_ms_in_chunk),
                        start_ms_in_chunk=segment.start_ms_in_chunk,
                        end_ms_in_chunk=segment.end_ms_in_chunk,
                        source_type="chunk_raw",
                    )
                )
                raw_segment_index += 1
                for word in segment.words:
                    raw_words.append(
                        {
                            "meeting_id": meeting_id,
                            "chunk_id": chunk_id,
                            "segment_id": None,
                            "word_index": raw_word_index,
                            "word_text": word.word_text,
                            "start_ms_in_meeting": _meeting_time(chunk_start_ms, word.start_ms_in_chunk) or 0,
                            "end_ms_in_meeting": _meeting_time(chunk_start_ms, word.end_ms_in_chunk) or 0,
                            "start_ms_in_chunk": word.start_ms_in_chunk,
                            "end_ms_in_chunk": word.end_ms_in_chunk,
                            "speaker_label": word.speaker_label,
                            "confidence": word.confidence,
                        }
                    )
                    raw_word_index += 1

                merged_candidate = _trim_segment_to_unique_region(
                    meeting_id=meeting_id,
                    transcription_run_id=transcription_run_id,
                    chunk=chunk,
                    segment=segment,
                    unique_start_ms=unique_start_ms,
                    unique_end_ms=unique_end_ms,
                )
                if merged_candidate is None:
                    dropped_segments += 1
                    dropped_words += len(segment.words)
                    continue
                if merged_segments and _can_merge(merged_segments[-1], merged_candidate):
                    merged_segments[-1] = _merge_segments(merged_segments[-1], merged_candidate)
                else:
                    merged_candidate["segment_index"] = len(merged_segments)
                    merged_segments.append(merged_candidate)

        return {
            "raw_segments": raw_segments,
            "raw_words": raw_words,
            "merged_segments": merged_segments,
            "report": {
                "chunk_count": len(chunk_rows),
                "raw_segment_count": len(raw_segments),
                "merged_segment_count": len(merged_segments),
                "word_count": len(raw_words),
                "dropped_segment_count": dropped_segments,
                "dropped_word_count": dropped_words,
                "average_confidence": _average([segment.get("confidence") for segment in merged_segments]),
                "dedupe_strategy": "trim_to_unique_chunk_region",
            },
        }


def _trim_segment_to_unique_region(
    *,
    meeting_id: int,
    transcription_run_id: int,
    chunk: dict[str, Any],
    segment: TranscriptSegment,
    unique_start_ms: int,
    unique_end_ms: int,
) -> dict[str, Any] | None:
    chunk_start_ms = int(chunk["start_ms"])
    if segment.words:
        kept_words = [
            word
            for word in segment.words
            if _intersects(
                _meeting_time(chunk_start_ms, word.start_ms_in_chunk),
                _meeting_time(chunk_start_ms, word.end_ms_in_chunk),
                unique_start_ms,
                unique_end_ms,
            )
        ]
        if not kept_words:
            return None
        return _segment_row(
            meeting_id=meeting_id,
            transcription_run_id=transcription_run_id,
            chunk_id=int(chunk["id"]),
            segment_index=0,
            text=" ".join(word.word_text for word in kept_words),
            speaker_label=kept_words[0].speaker_label,
            confidence=_average([word.confidence for word in kept_words]),
            start_ms_in_meeting=_meeting_time(chunk_start_ms, kept_words[0].start_ms_in_chunk),
            end_ms_in_meeting=_meeting_time(chunk_start_ms, kept_words[-1].end_ms_in_chunk),
            start_ms_in_chunk=kept_words[0].start_ms_in_chunk,
            end_ms_in_chunk=kept_words[-1].end_ms_in_chunk,
            source_type="merged",
        )

    midpoint = ((_meeting_time(chunk_start_ms, segment.start_ms_in_chunk) or unique_start_ms) + (_meeting_time(chunk_start_ms, segment.end_ms_in_chunk) or unique_end_ms)) // 2
    if midpoint < unique_start_ms or midpoint > unique_end_ms:
        return None
    return _segment_row(
        meeting_id=meeting_id,
        transcription_run_id=transcription_run_id,
        chunk_id=int(chunk["id"]),
        segment_index=0,
        text=segment.text,
        speaker_label=segment.speaker_label,
        confidence=segment.confidence,
        start_ms_in_meeting=_meeting_time(chunk_start_ms, segment.start_ms_in_chunk) or unique_start_ms,
        end_ms_in_meeting=_meeting_time(chunk_start_ms, segment.end_ms_in_chunk) or unique_end_ms,
        start_ms_in_chunk=segment.start_ms_in_chunk,
        end_ms_in_chunk=segment.end_ms_in_chunk,
        source_type="merged",
    )


def _segment_row(
    *,
    meeting_id: int,
    transcription_run_id: int,
    chunk_id: int,
    segment_index: int,
    text: str,
    speaker_label: str | None,
    confidence: float | None,
    start_ms_in_meeting: int | None,
    end_ms_in_meeting: int | None,
    start_ms_in_chunk: int | None,
    end_ms_in_chunk: int | None,
    source_type: str,
) -> dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "transcription_run_id": transcription_run_id,
        "chunk_id": chunk_id,
        "segment_index": segment_index,
        "speaker_label": speaker_label,
        "speaker_name": None,
        "text": text.strip(),
        "start_ms_in_meeting": start_ms_in_meeting or 0,
        "end_ms_in_meeting": end_ms_in_meeting or start_ms_in_meeting or 0,
        "start_ms_in_chunk": start_ms_in_chunk,
        "end_ms_in_chunk": end_ms_in_chunk,
        "confidence": confidence,
        "source_type": source_type,
    }


def _meeting_time(chunk_start_ms: int, relative_ms: int | None) -> int | None:
    return None if relative_ms is None else chunk_start_ms + relative_ms


def _intersects(start_ms: int | None, end_ms: int | None, window_start_ms: int, window_end_ms: int) -> bool:
    actual_start = start_ms if start_ms is not None else end_ms
    actual_end = end_ms if end_ms is not None else start_ms
    if actual_start is None or actual_end is None:
        return False
    return actual_end >= window_start_ms and actual_start <= window_end_ms


def _can_merge(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("speaker_label") == right.get("speaker_label") and right["start_ms_in_meeting"] - left["end_ms_in_meeting"] <= 750


def _merge_segments(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        **left,
        "text": f"{left['text']} {right['text']}".strip(),
        "end_ms_in_meeting": right["end_ms_in_meeting"],
        "end_ms_in_chunk": right.get("end_ms_in_chunk"),
        "confidence": _average([left.get("confidence"), right.get("confidence")]),
    }


def _average(values: list[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 4) if numbers else None
