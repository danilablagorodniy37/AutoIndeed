"""Draft answers to application questions using Claude, grounded in the resume."""
from __future__ import annotations

import os
from pathlib import Path

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


SYSTEM = (
    "You help a job applicant fill out an online job application. "
    "You are given the applicant's resume/profile and a single application question. "
    "Answer ONLY as the applicant would type into the form field — no preamble, no "
    "quotes, no markdown, no explanation. Be concise and truthful to the resume. "
    "If the question expects a number, reply with just the number. "
    "If you genuinely cannot determine an answer from the resume, reply exactly: UNKNOWN"
)


class Drafter:
    """Wraps the Anthropic client. Cheaply degrades to disabled if no key/SDK."""

    def __init__(self, model: str = "claude-opus-4-8", effort: str = "low",
                 resume_text: str = "", profile: dict | None = None):
        self.model = model
        self.effort = effort
        self.resume_text = resume_text
        self.profile = profile or {}
        self.enabled = bool(anthropic) and bool(os.environ.get("ANTHROPIC_API_KEY"))
        self._client = anthropic.Anthropic() if self.enabled else None

    def draft(self, question: str, options: list[str] | None = None) -> str | None:
        """Return a drafted answer string, or None if unavailable/unknown."""
        if not self.enabled:
            return None

        ctx_lines = [f"{k}: {v}" for k, v in self.profile.items() if v]
        profile_block = "\n".join(ctx_lines)
        opt_block = ""
        if options:
            opt_block = (
                "\n\nThis is a multiple-choice field. Reply with EXACTLY one of "
                "these options, copied verbatim:\n- " + "\n- ".join(options)
            )

        user = (
            f"=== APPLICANT PROFILE ===\n{profile_block}\n\n"
            f"=== RESUME ===\n{self.resume_text or '(no resume text provided)'}\n\n"
            f"=== QUESTION ===\n{question}{opt_block}"
        )

        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                system=SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # network/auth/etc — never crash the run
            print(f"[warn] AI draft failed: {exc}")
            return None

        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()

        if not text or text.upper() == "UNKNOWN":
            return None
        if options:
            # Coerce to a real option if the model paraphrased.
            for opt in options:
                if opt.strip().lower() == text.strip().lower():
                    return opt
            for opt in options:
                if text.strip().lower() in opt.strip().lower():
                    return opt
            return None
        return text


def read_resume_text(resume_path: Path | None) -> str:
    """Best-effort plain-text extraction of the resume for grounding the AI.

    Order: an adjacent resume.txt > a .txt resume > extracted PDF text (pypdf).
    """
    if resume_path is None:
        return ""
    txt_sibling = resume_path.with_suffix(".txt")
    if txt_sibling.exists():
        return txt_sibling.read_text(encoding="utf-8", errors="ignore")
    if resume_path.suffix.lower() == ".txt" and resume_path.exists():
        return resume_path.read_text(encoding="utf-8", errors="ignore")
    if resume_path.suffix.lower() == ".pdf" and resume_path.exists():
        return _extract_pdf_text(resume_path)
    return ""


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("[warn] pypdf not installed; PDF resume not parsed. "
              "Run `pip install pypdf` or drop a resume.txt next to the PDF.")
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not extract PDF text: {exc}")
        return ""
