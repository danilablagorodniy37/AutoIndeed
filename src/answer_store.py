"""Persistent store of answered questions.

Every question we answer (from config, AI, or a manual edit) is saved here keyed
by a normalized form of the question text. On future questions we look here FIRST
and reuse a previous answer instead of re-deriving it. The store accrues over time
into your personal Q&A knowledge base.

Format on disk (answers_store.json):
    {
      "entries": [
        {"question": "...", "norm": "...", "answer": "...",
         "kind": "text|choice", "source": "config|ai|manual", "uses": 3}
      ]
    }
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "answers_store.json"

# How similar a stored question must be to count as the same question (0..1).
MATCH_THRESHOLD = 0.86

_STOPWORDS = {
    "the", "a", "an", "of", "to", "for", "is", "are", "do", "does", "you",
    "your", "please", "this", "that", "in", "on", "at", "with", "have", "has",
    "what", "how", "many", "much", "and", "or", "we", "our",
}


def normalize(question: str) -> str:
    """Lowercase, strip punctuation/stopwords so phrasing differences collapse."""
    q = question.lower()
    q = re.sub(r"[^a-z0-9\s]", " ", q)
    tokens = [t for t in q.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


@dataclass
class Entry:
    question: str
    norm: str
    answer: str
    kind: str = "text"          # "text" or "choice"
    source: str = "config"      # where the answer came from
    uses: int = 0

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "norm": self.norm,
            "answer": self.answer,
            "kind": self.kind,
            "source": self.source,
            "uses": self.uses,
        }


class AnswerStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        self.entries: list[Entry] = []
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] could not read answer store ({exc}); starting empty.")
            return
        for e in data.get("entries", []):
            self.entries.append(
                Entry(
                    question=e.get("question", ""),
                    norm=e.get("norm") or normalize(e.get("question", "")),
                    answer=e.get("answer", ""),
                    kind=e.get("kind", "text"),
                    source=e.get("source", "config"),
                    uses=int(e.get("uses", 0)),
                )
            )

    def lookup(self, question: str, options: list[str] | None = None) -> Entry | None:
        """Return the best stored match for `question`, or None.

        If `options` is given (a multiple-choice field), the stored answer must be
        one of the current options to be reusable.
        """
        norm = normalize(question)
        if not norm:
            return None
        best: Entry | None = None
        best_score = 0.0
        for e in self.entries:
            score = SequenceMatcher(None, norm, e.norm).ratio()
            # Boost when one normalized question fully contains the other.
            if norm in e.norm or e.norm in norm:
                score = max(score, 0.9)
            if score > best_score:
                best_score, best = score, e
        if best is None or best_score < MATCH_THRESHOLD:
            return None
        if options:
            if not _option_match(best.answer, options):
                return None
        return best

    def remember(self, question: str, answer: str, kind: str = "text",
                 source: str = "ai") -> None:
        """Insert or update an entry. Updating refreshes the answer + bumps uses."""
        if not answer:
            return
        norm = normalize(question)
        for e in self.entries:
            if e.norm == norm:
                e.answer = answer
                e.kind = kind
                e.source = source
                e.uses += 1
                self._dirty = True
                return
        self.entries.append(
            Entry(question=question, norm=norm, answer=answer, kind=kind,
                  source=source, uses=1)
        )
        self._dirty = True

    def bump(self, entry: Entry) -> None:
        entry.uses += 1
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        tmp = self.path.with_suffix(".tmp")
        payload = {"entries": [e.to_dict() for e in self.entries]}
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False

    def __len__(self) -> int:
        return len(self.entries)


def _option_match(answer: str, options: list[str]) -> str | None:
    """Return the option that best matches a stored answer, if any."""
    al = answer.strip().lower()
    for opt in options:
        if opt.strip().lower() == al:
            return opt
    for opt in options:
        ol = opt.strip().lower()
        if al and (al in ol or ol in al):
            return opt
    return None
