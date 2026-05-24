"""Rule-based post-Writer linter (banned phrases, length, reading level)."""

from __future__ import annotations

import re

from app.domain.models import EditorReport, EditorViolation, WriterOutput
from app.services.brand import brand_banned_phrases, brand_max_tweet_chars

_SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")
_MAX_AVG_WORDS_PER_SENTENCE = 22
_MAX_SENTENCE_WORDS = 40


def _sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = _SENTENCE_SPLIT.split(stripped)
    return [p.strip() for p in parts if p.strip()]


def _word_count(s: str) -> int:
    return len(s.split())


def _find_banned(text: str, banned: list[str], location: str) -> list[EditorViolation]:
    violations: list[EditorViolation] = []
    lower = text.lower()
    for phrase in banned:
        p = phrase.strip()
        if not p:
            continue
        if p.lower() in lower:
            violations.append(
                EditorViolation(
                    rule="banned_phrase",
                    message=f'Banned phrase "{p}" found',
                    location=location,
                )
            )
    return violations


def _check_reading_level(blog_post: str) -> list[EditorViolation]:
    violations: list[EditorViolation] = []
    sentences = _sentences(blog_post)
    if not sentences:
        return violations

    counts = [_word_count(s) for s in sentences]
    avg = sum(counts) / len(counts)
    if avg > _MAX_AVG_WORDS_PER_SENTENCE:
        violations.append(
            EditorViolation(
                rule="reading_level",
                message=(
                    f"Average sentence length {avg:.1f} words exceeds "
                    f"{_MAX_AVG_WORDS_PER_SENTENCE} (simplify for general audience)"
                ),
                location="blog",
            )
        )
    for i, (sentence, wc) in enumerate(zip(sentences, counts)):
        if wc > _MAX_SENTENCE_WORDS:
            violations.append(
                EditorViolation(
                    rule="reading_level",
                    message=f"Sentence {i + 1} has {wc} words (max {_MAX_SENTENCE_WORDS})",
                    location="blog",
                )
            )
    return violations


class EditorLinter:
    """Deterministic style checks; does not block the pipeline."""

    def lint(self, writer_out: WriterOutput) -> EditorReport:
        violations: list[EditorViolation] = []
        banned = brand_banned_phrases()
        max_tweet = brand_max_tweet_chars()

        violations.extend(_find_banned(writer_out.blog_post, banned, "blog"))
        for i, tweet in enumerate(writer_out.tweets):
            violations.extend(_find_banned(tweet, banned, f"tweet_{i + 1}"))
            if len(tweet) > max_tweet:
                violations.append(
                    EditorViolation(
                        rule="tweet_length",
                        message=f"Tweet {i + 1} is {len(tweet)} chars (max {max_tweet})",
                        location=f"tweet_{i + 1}",
                    )
                )

        violations.extend(_check_reading_level(writer_out.blog_post))

        if len(writer_out.tweets) != 3:
            violations.append(
                EditorViolation(
                    rule="tweet_count",
                    message=f"Expected 3 tweets, got {len(writer_out.tweets)}",
                    location="tweets",
                )
            )

        return EditorReport(passed=len(violations) == 0, violations=violations)
