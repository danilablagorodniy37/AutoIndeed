"""Load and validate the YAML config."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    raw: dict[str, Any]

    @property
    def search(self) -> dict[str, Any]:
        return self.raw["search"]

    @property
    def behavior(self) -> dict[str, Any]:
        return self.raw["behavior"]

    @property
    def profile(self) -> dict[str, Any]:
        return self.raw["profile"]

    @property
    def answers(self) -> dict[str, str]:
        return {k: str(v) for k, v in self.raw.get("answers", {}).items()}

    @property
    def ai(self) -> dict[str, Any]:
        return self.raw.get("ai", {})

    @property
    def mode(self) -> str:
        return self.behavior.get("mode", "review")

    @property
    def resume_path(self) -> Path | None:
        p = self.profile.get("resume_path")
        if not p:
            return None
        path = Path(p)
        if not path.is_absolute():
            path = ROOT / path
        return path


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found at {path}.\n"
            "Copy config.example.yaml to config.yaml and fill it in."
        )
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    cfg = Config(raw=raw)

    # Sanity checks that save a lot of confusion later.
    mode = cfg.mode
    if mode not in {"review", "auto", "collect"}:
        raise ValueError(f"behavior.mode must be review|auto|collect, got {mode!r}")

    if mode != "collect":
        rp = cfg.resume_path
        if rp is None or not rp.exists():
            raise FileNotFoundError(
                f"resume_path does not exist: {rp}. "
                "Set profile.resume_path in config.yaml to a real file."
            )

    if not os.environ.get("ANTHROPIC_API_KEY") and cfg.ai.get("draft_unknown", True) and mode != "collect":
        # Not fatal — engine falls back to config-only answers — but warn.
        print(
            "[warn] ANTHROPIC_API_KEY is not set. AI answer drafting is disabled; "
            "unknown free-text questions will be left blank."
        )

    return cfg
