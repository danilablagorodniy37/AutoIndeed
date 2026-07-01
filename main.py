"""Indeed auto-apply — entry point.

Usage:
    python main.py                 # use config.yaml
    python main.py --config x.yaml
    python main.py --dry-run       # force collect mode (no form filling)

The answer store (.secrets/answers_store.json) is checked first for every question and
grows over time so repeated questions are answered instantly without the AI.
"""
from __future__ import annotations

import argparse
import sys

from src.answer_store import AnswerStore
from src.answers import AnswerEngine
from src.config import load_config
from src.indeed import IndeedBot
from src.llm import Drafter, read_resume_text


def main() -> int:
    ap = argparse.ArgumentParser(description="Semi-automated Indeed job applier")
    ap.add_argument("--config", default="config.yaml", help="path to config YAML")
    ap.add_argument("--dry-run", action="store_true",
                    help="force collect mode: gather jobs, fill nothing")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.dry_run:
        cfg.raw["behavior"]["mode"] = "collect"

    store = AnswerStore()
    print(f"[info] answer store loaded: {len(store)} saved answers")

    resume_text = read_resume_text(cfg.resume_path)
    drafter = Drafter(
        model=cfg.ai.get("model", "claude-opus-4-8"),
        effort=cfg.ai.get("effort", "low"),
        resume_text=resume_text,
        profile=cfg.profile,
    )
    if not drafter.enabled and cfg.mode != "collect":
        print("[info] AI drafting disabled (no ANTHROPIC_API_KEY) — store + config only")

    engine = AnswerEngine(
        store=store,
        config_answers=cfg.answers,
        profile=cfg.profile,
        drafter=drafter,
        draft_unknown=cfg.ai.get("draft_unknown", True),
    )

    bot = IndeedBot(cfg, engine)
    try:
        results = bot.run()
    finally:
        store.save()
        print(f"[info] answer store saved: {len(store)} answers")

    _report(results)
    return 0


def _report(results) -> None:
    print("\n==================== SUMMARY ====================")
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        print(f"  [{r.status:9}] {r.title} @ {r.company}"
              + (f"  — {r.note}" if r.note else ""))
    print("------------------------------------------------")
    for status, n in sorted(by_status.items()):
        print(f"  {status}: {n}")
    print("================================================")


if __name__ == "__main__":
    sys.exit(main())
