"""Resolve an application question into an answer.

Resolution order (this is the heart of the system):
    1. Persistent store  -> if we've answered this (or a near-identical) question
                            before, reuse it. No AI call, no guessing.
    2. Config answers    -> keyword-matched against the `answers:` block + profile.
    3. AI draft          -> Claude answers from the resume (if enabled).

Whatever we resolve is written back into the store so it is reused next time.
Returns an `Answer` carrying the value and where it came from, so the caller can
decide whether the job is safe to auto-submit (store/config = known; ai = review).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .answer_store import AnswerStore
from .llm import Drafter

# Maps config-answer keys to keyword sets found in real Indeed questions.
CONFIG_KEYWORDS: dict[str, list[str]] = {
    "years_of_experience": [
        "years of experience", "years experience", "how many years",
        "experience do you have", "years in", "year of experience",
    ],
    "work_authorization": [
        "authorized to work", "authorised to work", "work authorization",
        "work authorisation", "legally authorized", "legally authorised",
        "right to work", "eligible to work", "permitted to work",
        "allowed to work", "entitled to work",
    ],
    "require_sponsorship": ["sponsorship", "sponsor", "visa", "tier 2", "skilled worker"],
    "willing_to_relocate": ["relocate", "relocation"],
    "notice_period": ["notice period", "notice"],
    "desired_salary": [
        "desired salary", "salary expectation", "expected salary", "compensation",
        "salary", "pay expectation", "what pay", "salary requirement",
    ],
    "available_start_date": [
        "start date", "available to start", "when can you start",
        "earliest start", "how soon can you start",
    ],
    "highest_education": [
        "education level", "highest education", "level of education",
        "degree", "qualification",
    ],
    "expected_hourly_rate": ["hourly rate", "rate per hour", "hourly", "day rate"],
}

# Profile fields directly fillable when a question clearly asks for them.
PROFILE_KEYWORDS: dict[str, list[str]] = {
    "first_name": ["first name"],
    "last_name": ["last name", "surname"],
    "full_name": ["full name", "your name"],
    "email": ["email"],
    "phone": ["phone", "mobile", "telephone"],
    "city": ["city", "where do you live", "location"],
    "country": ["country"],
    "linkedin": ["linkedin"],
    "website": ["website", "portfolio", "personal site"],
}


@dataclass
class Answer:
    value: str
    source: str          # "store" | "config" | "profile" | "ai"
    known: bool          # True if from store/config/profile (safe to auto-submit)


class AnswerEngine:
    def __init__(self, store: AnswerStore, config_answers: dict[str, str],
                 profile: dict[str, str], drafter: Drafter,
                 draft_unknown: bool = True):
        self.store = store
        self.config_answers = config_answers
        self.profile = profile
        self.drafter = drafter
        self.draft_unknown = draft_unknown

    def resolve(self, question: str, options: list[str] | None = None,
                kind: str = "text") -> Answer | None:
        """Resolve a question to an Answer, or None if we have nothing."""
        # 1) Persistent store — reuse a past answer.
        hit = self.store.lookup(question, options)
        if hit is not None:
            value = _coerce_option(hit.answer, options) if options else hit.answer
            if value:
                self.store.bump(hit)
                return Answer(value=value, source="store", known=True)

        # 2) Config answers + profile fields.
        cfg = self._from_config(question, options)
        if cfg is not None:
            self.store.remember(question, cfg.value, kind=kind, source=cfg.source)
            return cfg

        # 3) AI draft from the resume.
        if self.draft_unknown:
            drafted = self.drafter.draft(question, options)
            if drafted:
                value = _coerce_option(drafted, options) if options else drafted
                if value:
                    self.store.remember(question, value, kind=kind, source="ai")
                    # AI answers are NOT "known" — they trigger a review pause.
                    return Answer(value=value, source="ai", known=False)

        return None

    def _from_config(self, question: str, options: list[str] | None) -> Answer | None:
        ql = question.lower()

        for key, words in CONFIG_KEYWORDS.items():
            if key in self.config_answers and any(w in ql for w in words):
                value = self.config_answers[key]
                if options:
                    coerced = _coerce_option(value, options)
                    if not coerced:
                        continue
                    value = coerced
                return Answer(value=value, source="config", known=True)

        for key, words in PROFILE_KEYWORDS.items():
            if self.profile.get(key) and any(w in ql for w in words):
                value = str(self.profile[key])
                if options:
                    coerced = _coerce_option(value, options)
                    if not coerced:
                        continue
                    value = coerced
                return Answer(value=value, source="profile", known=True)

        # Yes/No questions with an obvious config default.
        if options and _is_yes_no(options):
            for key, words in CONFIG_KEYWORDS.items():
                if key in self.config_answers and any(w in ql for w in words):
                    coerced = _coerce_option(self.config_answers[key], options)
                    if coerced:
                        return Answer(value=coerced, source="config", known=True)
        return None


def _coerce_option(answer: str, options: list[str]) -> str | None:
    al = answer.strip().lower()
    for opt in options:
        if opt.strip().lower() == al:
            return opt
    # yes/no shorthand
    if al in {"yes", "y", "true"}:
        for opt in options:
            if opt.strip().lower().startswith("yes"):
                return opt
    if al in {"no", "n", "false"}:
        for opt in options:
            if opt.strip().lower().startswith("no"):
                return opt
    for opt in options:
        if al and (al in opt.strip().lower() or opt.strip().lower() in al):
            return opt
    return None


def _is_yes_no(options: list[str]) -> bool:
    low = {o.strip().lower() for o in options}
    return bool(low) and low <= {"yes", "no"} | {o for o in low if re.match(r"^(yes|no)\b", o)}
