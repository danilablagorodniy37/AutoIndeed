"""Seed answers_store.json with the most common Indeed screening questions.

Personal answers (salary, experience, work auth, contact details) are pulled from
your config.yaml so they're correct for you. The rest get safe, low-risk generic
defaults you can edit afterwards in answers_store.json.

Usage:
    python seed.py                 # add seeds that aren't already in the store
    python seed.py --force         # overwrite existing entries with seed values
    python seed.py --config x.yaml

Seeded entries are marked source="seed" so you can find/review them. They count as
"known" answers, so seeded jobs become eligible for auto-submit.
"""
from __future__ import annotations

import argparse
import sys

from src.answer_store import AnswerStore
from src.config import load_config

# Each entry: (question, kind, source_spec)
#   source_spec ("cfg", key)     -> value from config.answers[key]
#   source_spec ("profile", key) -> value from config.profile[key]
#   source_spec ("lit", value)   -> literal default
SEED: list[tuple[str, str, tuple[str, str]]] = [
    # --- experience ---------------------------------------------------------
    ("How many years of work experience do you have?", "text", ("cfg", "years_of_experience")),
    ("How many years of professional experience do you have?", "text", ("cfg", "years_of_experience")),
    ("How many years of experience do you have in this field?", "text", ("cfg", "years_of_experience")),

    # --- work authorization -------------------------------------------------
    ("Are you legally authorized to work in this country?", "choice", ("cfg", "work_authorization")),
    ("Are you authorised to work in the UK?", "choice", ("cfg", "work_authorization")),
    ("Do you have the right to work in this country?", "choice", ("cfg", "work_authorization")),
    ("Will you now or in the future require visa sponsorship?", "choice", ("cfg", "require_sponsorship")),
    ("Do you require sponsorship to work in this country?", "choice", ("cfg", "require_sponsorship")),

    # --- logistics ----------------------------------------------------------
    ("Are you willing to relocate?", "choice", ("cfg", "willing_to_relocate")),
    ("What is your notice period?", "text", ("cfg", "notice_period")),
    ("When can you start?", "text", ("cfg", "available_start_date")),
    ("What is your earliest available start date?", "text", ("cfg", "available_start_date")),

    # --- compensation -------------------------------------------------------
    ("What are your salary expectations?", "text", ("cfg", "desired_salary")),
    ("What is your desired salary?", "text", ("cfg", "desired_salary")),
    ("What is your expected hourly rate?", "text", ("cfg", "expected_hourly_rate")),

    # --- education ----------------------------------------------------------
    ("What is your highest level of education?", "text", ("cfg", "highest_education")),

    # --- contact / identity (from profile) ----------------------------------
    ("What is your full name?", "text", ("profile", "full_name")),
    ("What is your email address?", "text", ("profile", "email")),
    ("What is your phone number?", "text", ("profile", "phone")),
    ("What city do you live in?", "text", ("profile", "city")),
    ("What is your LinkedIn profile?", "text", ("profile", "linkedin")),

    # --- safe generic yes/no defaults (edit if any don't apply to you) ------
    ("Are you at least 18 years old?", "choice", ("lit", "Yes")),
    ("Do you have a valid driver's license?", "choice", ("lit", "Yes")),
    ("Do you have reliable transportation?", "choice", ("lit", "Yes")),
    ("Are you willing to undergo a background check?", "choice", ("lit", "Yes")),
    ("Are you comfortable commuting to this location?", "choice", ("lit", "Yes")),
    ("Are you a fluent English speaker?", "choice", ("lit", "Yes")),
    ("Can you reliably commute or plan to relocate before starting work?", "choice", ("lit", "Yes")),
    ("Do you have professional working proficiency in English?", "choice", ("lit", "Yes")),
]


def resolve(spec: tuple[str, str], cfg) -> str | None:
    kind, key = spec
    if kind == "lit":
        return key
    if kind == "cfg":
        return cfg.answers.get(key) or None
    if kind == "profile":
        val = cfg.profile.get(key)
        return str(val) if val else None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed the answer store")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing store entries with seed values")
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = AnswerStore()
    before = len(store)

    added = skipped = 0
    for question, kind, spec in SEED:
        value = resolve(spec, cfg)
        if not value:
            continue  # no config value to seed from
        existing = store.lookup(question)
        if existing is not None and not args.force:
            skipped += 1
            continue
        store.remember(question, value, kind=kind, source="seed")
        added += 1

    store.save()
    print(f"[seed] config: {args.config}")
    print(f"[seed] added/updated {added}, skipped {skipped} already-present")
    print(f"[seed] store size: {before} -> {len(store)}")
    print("[seed] review/edit answers in answers_store.json (source: \"seed\").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
