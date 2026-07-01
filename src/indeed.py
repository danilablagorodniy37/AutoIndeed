"""Indeed search + apply automation via Playwright.

IMPORTANT / HONEST CAVEATS
- Indeed's ToS prohibits bots; they use anti-bot detection + CAPTCHA. This runs a
  REAL browser with a persistent profile so your login sticks and you stay in the
  loop. It is a semi-automated assistant, not a guaranteed hands-off pipeline.
- Indeed's DOM changes often. All selectors live in the SELECTORS dict below so you
  can update them in one place when something breaks.
"""
from __future__ import annotations

import random
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import (
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from .answers import AnswerEngine
from .config import Config, ROOT

USER_DATA_DIR = ROOT / ".browser_profile"

# Centralized, fragile-by-nature selectors. Update here when Indeed changes.
SELECTORS = {
    "job_card": "div.job_seen_beacon, div.cardOutline",
    "easy_apply_badge": "text=/Easily apply|Easy apply|Indeed Apply/i",
    "apply_button": "button#indeedApplyButton, button:has-text('Apply now'), [aria-label*='Apply']",
    # Within the Indeed Apply (smartapply) flow:
    "continue_button": "button:has-text('Continue'), button:has-text('Next')",
    "review_button": "button:has-text('Review your application')",
    "submit_button": "button:has-text('Submit application'), button:has-text('Submit your application')",
    "question_group": "[data-testid='questions'] fieldset, fieldset, .ia-Questions-item",
}


@dataclass
class JobResult:
    title: str
    company: str
    url: str
    status: str = "pending"        # applied | review | skipped | error | collected
    note: str = ""
    questions: list[str] = field(default_factory=list)


class IndeedBot:
    def __init__(self, cfg: Config, engine: AnswerEngine):
        self.cfg = cfg
        self.engine = engine
        self.results: list[JobResult] = []

    # ---- lifecycle ---------------------------------------------------------
    def run(self) -> list[JobResult]:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=False,                      # must be visible for login/CAPTCHA
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                self._ensure_logged_in(page)
                jobs = self._search(page)
                for job in jobs[: self.cfg.search.get("max_jobs", 15)]:
                    self._process_job(ctx, job)
            finally:
                ctx.close()
        return self.results

    # ---- login -------------------------------------------------------------
    def _ensure_logged_in(self, page: Page) -> None:
        domain = self.cfg.search.get("domain", "www.indeed.com")
        page.goto(f"https://{domain}/", wait_until="domcontentloaded")
        self._sleep()
        if "Sign in" in page.content() or "/account/login" in page.url:
            print(
                "\n>>> Please sign in to Indeed in the opened browser window.\n"
                ">>> Solve any CAPTCHA. The login is saved to the local profile for\n"
                ">>> next time. Press Enter here once you're signed in..."
            )
            input()

    # ---- search ------------------------------------------------------------
    def _search(self, page: Page) -> list[JobResult]:
        s = self.cfg.search
        params = {
            "q": s["query"],
            "l": s.get("location", ""),
            "fromage": str(s.get("posted_within_days", 7)),
            "sc": "0kf:attr(DSQF7);",  # Indeed's "Easily apply" filter token
        }
        url = f"https://{s.get('domain', 'www.indeed.com')}/jobs?" + urllib.parse.urlencode(params)
        page.goto(url, wait_until="domcontentloaded")
        self._sleep()

        jobs: list[JobResult] = []
        cards = page.locator(SELECTORS["job_card"])
        count = cards.count()
        print(f"[info] found {count} job cards on first page")
        for i in range(count):
            card = cards.nth(i)
            try:
                title_el = card.locator("h2 a, a.jcs-JobTitle").first
                title = (title_el.inner_text(timeout=2000) or "").strip()
                href = title_el.get_attribute("href") or ""
                if href and href.startswith("/"):
                    href = f"https://{s.get('domain', 'www.indeed.com')}{href}"
                company = ""
                comp_el = card.locator("[data-testid='company-name'], span.companyName")
                if comp_el.count():
                    company = (comp_el.first.inner_text() or "").strip()
                if title and href:
                    jobs.append(JobResult(title=title, company=company, url=href))
            except PWTimeout:
                continue
        return jobs

    # ---- per-job -----------------------------------------------------------
    def _process_job(self, ctx, job: JobResult) -> None:
        if self.cfg.mode == "collect":
            job.status = "collected"
            self.results.append(job)
            print(f"[collect] {job.title} @ {job.company} -> {job.url}")
            return

        page = ctx.new_page()
        try:
            page.goto(job.url, wait_until="domcontentloaded")
            self._sleep()

            apply_btn = page.locator(SELECTORS["apply_button"]).first
            if not apply_btn.count():
                job.status = "skipped"
                job.note = "no Indeed-Apply button (likely external apply)"
                print(f"[skip] {job.title}: {job.note}")
                return

            apply_btn.click()
            self._sleep()
            self._walk_application(page, job)
        except PWTimeout as exc:
            job.status = "error"
            job.note = f"timeout: {exc}"
            print(f"[error] {job.title}: {job.note}")
        except Exception as exc:  # noqa: BLE001 keep the run alive
            job.status = "error"
            job.note = str(exc)
            print(f"[error] {job.title}: {job.note}")
        finally:
            self.results.append(job)
            page.close()

    def _walk_application(self, page: Page, job: JobResult) -> None:
        """Step through the Indeed Apply flow filling each page of questions."""
        had_unknown = False
        pages_seen = 0
        max_pages = 8

        while pages_seen < max_pages:
            pages_seen += 1
            self._sleep()
            self._maybe_upload_resume(page)
            unknown = self._fill_visible_questions(page, job)
            had_unknown = had_unknown or unknown

            # Decide which navigation button is present.
            submit = page.locator(SELECTORS["submit_button"]).first
            review = page.locator(SELECTORS["review_button"]).first
            cont = page.locator(SELECTORS["continue_button"]).first

            if submit.count():
                self._finish(page, job, submit, pages=pages_seen,
                             had_unknown=had_unknown)
                return
            if review.count():
                review.click()
                continue
            if cont.count():
                cont.click()
                continue

            # No nav button -> either done or an unexpected screen.
            job.status = "review"
            job.note = "could not find a Continue/Submit button — needs manual review"
            self._review_pause(job)
            return

        job.status = "review"
        job.note = "too many application pages — left for manual review"
        self._review_pause(job)

    def _finish(self, page: Page, job: JobResult, submit_btn,
                pages: int, had_unknown: bool) -> None:
        """Decide whether to auto-submit or pause for review.

        In `auto` mode we submit any application (single OR multi-page) where every
        answer was known (store/config/profile). If AI-drafted answers were used,
        we only auto-submit when `auto_submit_with_ai` is enabled in config.
        """
        allow_ai = bool(self.cfg.behavior.get("auto_submit_with_ai", False))
        auto = self.cfg.mode == "auto" and (not had_unknown or allow_ai)
        if auto:
            submit_btn.click()
            self._sleep()
            job.status = "applied"
            kind = "known answers" if not had_unknown else "incl. AI answers"
            job.note = f"auto-submitted ({pages} page(s), {kind})"
            print(f"[applied] {job.title} @ {job.company} — {job.note}")
        else:
            job.status = "review"
            job.note = "ready to submit — paused for review (AI-drafted answers present)"
            print(f"[review] {job.title}: {job.note}")
            self._review_pause(job)

    # ---- field filling -----------------------------------------------------
    def _fill_visible_questions(self, page: Page, job: JobResult) -> bool:
        """Fill every question on the current screen. Returns True if any answer
        was AI-drafted/unknown (so the job should be reviewed, not auto-submitted)."""
        had_unknown = False

        # Text inputs / textareas with an associated label.
        for loc in page.locator("input[type='text'], input[type='tel'], "
                                 "input[type='email'], input[type='number'], "
                                 "textarea").all():
            try:
                if not loc.is_visible() or (loc.input_value() or "").strip():
                    continue
            except Exception:
                continue
            label = self._label_for(page, loc)
            if not label:
                continue
            ans = self.engine.resolve(label, kind="text")
            if ans:
                loc.fill(ans.value)
                job.questions.append(f"{label} = {ans.value} [{ans.source}]")
                had_unknown = had_unknown or not ans.known
                self._sleep(0.3, 1.0)

        # Radio / select groups (multiple choice).
        had_unknown |= self._fill_choice_groups(page, job)
        return had_unknown

    def _fill_choice_groups(self, page: Page, job: JobResult) -> bool:
        had_unknown = False
        fieldsets = page.locator("fieldset")
        for i in range(fieldsets.count()):
            fs = fieldsets.nth(i)
            try:
                legend = fs.locator("legend").first
                question = (legend.inner_text() or "").strip() if legend.count() else ""
                radios = fs.locator("input[type='radio']")
                n = radios.count()
                if not question or n == 0:
                    continue
                # Already answered?
                if any(radios.nth(j).is_checked() for j in range(n)):
                    continue
                options = []
                for j in range(n):
                    lbl = self._label_for(page, radios.nth(j))
                    options.append(lbl or f"option{j}")
                ans = self.engine.resolve(question, options=options, kind="choice")
                if ans:
                    for j, opt in enumerate(options):
                        if opt == ans.value:
                            radios.nth(j).check()
                            job.questions.append(f"{question} = {opt} [{ans.source}]")
                            had_unknown = had_unknown or not ans.known
                            break
            except Exception:
                continue
        return had_unknown

    def _label_for(self, page: Page, loc) -> str:
        """Best-effort label text for an input element."""
        try:
            el_id = loc.get_attribute("id")
            if el_id:
                lab = page.locator(f"label[for='{el_id}']")
                if lab.count():
                    return (lab.first.inner_text() or "").strip()
            aria = loc.get_attribute("aria-label")
            if aria:
                return aria.strip()
            placeholder = loc.get_attribute("placeholder")
            if placeholder:
                return placeholder.strip()
            # Fallback: nearest preceding label/text.
            handle = loc.evaluate(
                "el => { const l = el.closest('label'); return l ? l.innerText : ''; }"
            )
            return (handle or "").strip()
        except Exception:
            return ""

    def _maybe_upload_resume(self, page: Page) -> None:
        rp = self.cfg.resume_path
        if rp is None:
            return
        file_input = page.locator("input[type='file']")
        if file_input.count():
            try:
                file_input.first.set_input_files(str(rp))
                self._sleep()
            except Exception:
                pass

    # ---- helpers -----------------------------------------------------------
    def _review_pause(self, job: JobResult) -> None:
        if self.cfg.mode == "auto":
            # In auto mode, don't block — just record and move on.
            return
        secs = int(self.cfg.behavior.get("review_pause_seconds", 120))
        print(
            f"\n>>> REVIEW: {job.title} @ {job.company}\n"
            f">>> Verify the filled answers in the browser, then submit manually.\n"
            f">>> Waiting up to {secs}s (press Enter to continue sooner)..."
        )
        self._wait_or_enter(secs)

    @staticmethod
    def _wait_or_enter(seconds: int) -> None:
        import select
        import sys
        if sys.platform.startswith("win"):
            # No select() on stdin in Windows; just sleep.
            time.sleep(seconds)
            return
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([sys.stdin], [], [], 1)
            if r:
                sys.stdin.readline()
                return

    def _sleep(self, lo: float | None = None, hi: float | None = None) -> None:
        lo = lo if lo is not None else self.cfg.behavior.get("min_delay", 1.5)
        hi = hi if hi is not None else self.cfg.behavior.get("max_delay", 4.0)
        time.sleep(random.uniform(lo, hi))
