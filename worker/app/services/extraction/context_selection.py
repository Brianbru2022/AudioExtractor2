from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "there",
    "this",
    "to",
    "was",
    "we",
    "will",
    "with",
}

FOCUS_TERMS = {
    "actions": {
        "action",
        "follow",
        "owner",
        "assign",
        "assigned",
        "deliver",
        "draft",
        "prepare",
        "send",
        "update",
        "need",
        "needs",
        "todo",
        "next",
        "deadline",
        "due",
    },
    "decisions": {
        "agree",
        "agreed",
        "approve",
        "approved",
        "decision",
        "decide",
        "decided",
        "proceed",
        "ship",
        "commit",
        "rollout",
        "plan",
    },
    "risks": {
        "risk",
        "issue",
        "blocker",
        "concern",
        "problem",
        "delay",
        "dependency",
        "unclear",
        "uncertain",
        "stuck",
        "slip",
    },
    "questions": {
        "question",
        "ask",
        "whether",
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "can",
        "should",
        "could",
    },
    "topics": set(),
}

FOCUS_PHRASES = {
    "actions": ("we need to", "someone should", "next step", "follow up", "please send", "owner"),
    "decisions": ("we decided", "decision is", "let's proceed", "we will proceed", "agreed to"),
    "risks": ("big risk", "main issue", "open risk", "there is a concern", "blocked by"),
    "questions": ("can we", "should we", "do we", "what if", "who will", "when will"),
}


@dataclass(slots=True)
class TranscriptBlock:
    index: int
    segment_ids: list[int]
    start_ms: int
    end_ms: int
    text: str
    keywords: set[str]
    gap_before_ms: int


@dataclass(slots=True)
class ContextWindow:
    index: int
    focus_labels: list[str]
    reason: str
    score: float
    segment_ids: list[int]
    start_ms: int
    end_ms: int


class ExtractionContextSelector:
    def select(
        self,
        segments: list[dict[str, Any]],
        *,
        max_segments_per_window: int,
    ) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
        if not segments:
            return [], {"mode": "empty", "blocks": [], "windows": []}

        if len(segments) <= max_segments_per_window:
            return [segments], {
                "mode": "single_window",
                "blocks": [],
                "windows": [
                    {
                        "index": 0,
                        "focus_labels": ["full_transcript"],
                        "reason": "transcript_fits_single_window",
                        "score": 1.0,
                        "segment_ids": [int(segment["id"]) for segment in segments],
                        "start_ms": int(segments[0]["start_ms_in_meeting"]),
                        "end_ms": int(segments[-1]["end_ms_in_meeting"]),
                    }
                ],
            }

        blocks = self._build_blocks(segments, max_segments_per_window=max(8, max_segments_per_window // 3))
        selected_ids, focus_debug = self._select_relevant_blocks(blocks)
        selected_ids = self._ensure_coverage(blocks, selected_ids, max_segments_per_window=max_segments_per_window)
        windows = self._merge_selected_blocks(blocks, selected_ids, max_segments_per_window=max_segments_per_window)
        if not windows:
            fallback = self._fixed_windows(segments, max_segments_per_window)
            return fallback, {
                "mode": "fixed_window_fallback",
                "blocks": [self._block_to_report(block) for block in blocks],
                "focus_debug": focus_debug,
                "windows": [],
            }

        segment_map = {int(segment["id"]): segment for segment in segments}
        realized_windows = [
            [segment_map[segment_id] for segment_id in window.segment_ids if segment_id in segment_map]
            for window in windows
        ]
        return realized_windows, {
            "mode": "retrieval_context_selection",
            "blocks": [self._block_to_report(block) for block in blocks],
            "focus_debug": focus_debug,
            "windows": [
                {
                    "index": window.index,
                    "focus_labels": window.focus_labels,
                    "reason": window.reason,
                    "score": round(window.score, 4),
                    "segment_ids": window.segment_ids,
                    "start_ms": window.start_ms,
                    "end_ms": window.end_ms,
                }
                for window in windows
            ],
        }

    def _build_blocks(self, segments: list[dict[str, Any]], *, max_segments_per_window: int) -> list[TranscriptBlock]:
        blocks: list[TranscriptBlock] = []
        current: list[dict[str, Any]] = []
        current_keywords: set[str] = set()

        for index, segment in enumerate(segments):
            segment_text = str(segment.get("text") or "")
            segment_keywords = _keywords(segment_text)
            if not current:
                current = [segment]
                current_keywords = set(segment_keywords)
                continue

            previous = current[-1]
            gap_before_ms = int(segment["start_ms_in_meeting"]) - int(previous["end_ms_in_meeting"])
            lexical_overlap = _jaccard(current_keywords, segment_keywords)
            should_split = (
                len(current) >= max_segments_per_window
                or gap_before_ms >= 90_000
                or (
                    len(current) >= 4
                    and gap_before_ms >= 20_000
                    and lexical_overlap < 0.08
                )
            )
            if should_split:
                blocks.append(self._make_block(len(blocks), current))
                current = [segment]
                current_keywords = set(segment_keywords)
            else:
                current.append(segment)
                current_keywords.update(segment_keywords)

            if index == len(segments) - 1 and current:
                blocks.append(self._make_block(len(blocks), current))

        if current and (not blocks or blocks[-1].segment_ids[-1] != int(current[-1]["id"])):
            blocks.append(self._make_block(len(blocks), current))
        return blocks

    def _make_block(self, index: int, segments: list[dict[str, Any]]) -> TranscriptBlock:
        start_ms = int(segments[0]["start_ms_in_meeting"])
        end_ms = int(segments[-1]["end_ms_in_meeting"])
        gap_before_ms = 0
        text = " ".join(str(segment.get("text") or "") for segment in segments)
        return TranscriptBlock(
            index=index,
            segment_ids=[int(segment["id"]) for segment in segments],
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            keywords=_keywords(text),
            gap_before_ms=gap_before_ms,
        )

    def _select_relevant_blocks(self, blocks: list[TranscriptBlock]) -> tuple[set[int], dict[str, Any]]:
        selected_ids: set[int] = set()
        focus_debug: dict[str, Any] = {}
        for focus in ("actions", "decisions", "risks", "questions", "topics"):
            rankings = []
            for block in blocks:
                score = self._score_block(block, focus)
                rankings.append(
                    {
                        "block_index": block.index,
                        "score": round(score, 4),
                        "segment_count": len(block.segment_ids),
                        "start_ms": block.start_ms,
                        "end_ms": block.end_ms,
                    }
                )
            rankings.sort(key=lambda item: (-item["score"], item["block_index"]))
            focus_debug[focus] = rankings[:6]

            chosen = [item["block_index"] for item in rankings if item["score"] > 0.6][:2]
            if not chosen and rankings and rankings[0]["score"] > 0.0:
                chosen = [rankings[0]["block_index"]]
            for block_index in chosen:
                selected_ids.add(block_index)
                if block_index > 0:
                    selected_ids.add(block_index - 1)
                if block_index < len(blocks) - 1:
                    selected_ids.add(block_index + 1)
        return selected_ids, focus_debug

    def _score_block(self, block: TranscriptBlock, focus: str) -> float:
        text = block.text.lower()
        tokens = block.keywords
        score = 0.0
        if focus == "topics":
            return min(2.0, 0.35 + (len(tokens) / 40.0))

        score += sum(1.0 for term in FOCUS_TERMS[focus] if term in tokens)
        score += sum(1.4 for phrase in FOCUS_PHRASES.get(focus, ()) if phrase in text)
        if focus == "questions" and "?" in text:
            score += 1.8
        if focus == "actions" and any(marker in text for marker in ("will ", "owner", "by ", "next step")):
            score += 0.8
        if focus == "decisions" and any(marker in text for marker in ("agreed", "decided", "proceed", "approved")):
            score += 1.1
        if focus == "risks" and any(marker in text for marker in ("risk", "issue", "concern", "blocked")):
            score += 1.0
        return score

    def _ensure_coverage(
        self,
        blocks: list[TranscriptBlock],
        selected_ids: set[int],
        *,
        max_segments_per_window: int,
    ) -> set[int]:
        if not blocks:
            return selected_ids

        if not selected_ids:
            stride = max(1, len(blocks) // 4)
            return set(range(0, len(blocks), stride))

        selected_segment_count = sum(len(blocks[index].segment_ids) for index in selected_ids)
        total_segment_count = sum(len(block.segment_ids) for block in blocks)
        target_coverage = 0.65 if total_segment_count > max_segments_per_window * 2 else 0.5
        if total_segment_count == 0 or (selected_segment_count / total_segment_count) >= target_coverage:
            return selected_ids

        remaining = [block.index for block in blocks if block.index not in selected_ids]
        stride = max(1, len(remaining) // 4) if remaining else 1
        for index in remaining[::stride]:
            selected_ids.add(index)
            selected_segment_count = sum(len(blocks[item].segment_ids) for item in selected_ids)
            if (selected_segment_count / total_segment_count) >= target_coverage:
                break
        return selected_ids

    def _merge_selected_blocks(
        self,
        blocks: list[TranscriptBlock],
        selected_ids: set[int],
        *,
        max_segments_per_window: int,
    ) -> list[ContextWindow]:
        if not selected_ids:
            return []

        merged_windows: list[ContextWindow] = []
        ordered_ids = sorted(selected_ids)
        current_group = [ordered_ids[0]]
        for block_index in ordered_ids[1:]:
            if block_index == current_group[-1] + 1:
                current_group.append(block_index)
            else:
                merged_windows.extend(self._split_group(blocks, current_group, max_segments_per_window))
                current_group = [block_index]
        merged_windows.extend(self._split_group(blocks, current_group, max_segments_per_window))
        return merged_windows

    def _split_group(
        self,
        blocks: list[TranscriptBlock],
        group: list[int],
        max_segments_per_window: int,
    ) -> list[ContextWindow]:
        windows: list[ContextWindow] = []
        current_ids: list[int] = []
        current_segments: list[int] = []
        for block_index in group:
            candidate_segments = current_segments + blocks[block_index].segment_ids
            if current_segments and len(candidate_segments) > max_segments_per_window:
                windows.append(self._window_from_blocks(blocks, current_ids, len(windows)))
                current_ids = [block_index]
                current_segments = list(blocks[block_index].segment_ids)
            else:
                current_ids.append(block_index)
                current_segments = candidate_segments
        if current_ids:
            windows.append(self._window_from_blocks(blocks, current_ids, len(windows)))
        return windows

    def _window_from_blocks(self, blocks: list[TranscriptBlock], block_ids: list[int], index: int) -> ContextWindow:
        segments: list[int] = []
        focus_labels: list[str] = []
        for block_id in block_ids:
            block = blocks[block_id]
            segments.extend(block.segment_ids)
            block_focuses = []
            for focus in ("actions", "decisions", "risks", "questions", "topics"):
                if self._score_block(block, focus) > 0.6:
                    block_focuses.append(focus)
            for focus in block_focuses:
                if focus not in focus_labels:
                    focus_labels.append(focus)
        first = blocks[block_ids[0]]
        last = blocks[block_ids[-1]]
        return ContextWindow(
            index=index,
            focus_labels=focus_labels or ["coverage"],
            reason="retrieval_selected_blocks",
            score=max(self._score_block(blocks[block_id], focus) for block_id in block_ids for focus in ("actions", "decisions", "risks", "questions", "topics")),
            segment_ids=segments,
            start_ms=first.start_ms,
            end_ms=last.end_ms,
        )

    def _fixed_windows(self, segments: list[dict[str, Any]], max_segments_per_window: int) -> list[list[dict[str, Any]]]:
        return [segments[index : index + max_segments_per_window] for index in range(0, len(segments), max_segments_per_window)]

    def _block_to_report(self, block: TranscriptBlock) -> dict[str, Any]:
        return {
            "index": block.index,
            "segment_ids": block.segment_ids,
            "start_ms": block.start_ms,
            "end_ms": block.end_ms,
            "keyword_count": len(block.keywords),
        }


def _keywords(text: str) -> set[str]:
    tokens = []
    current = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return {token for token in tokens if len(token) > 2 and token not in STOPWORDS}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
