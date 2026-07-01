# Indeed Auto-Apply (semi-automated)

A browser assistant that searches Indeed, finds **Indeed Apply** jobs, fills the
application forms from your profile + a growing answer store + Claude, and
auto-submits the simple ones. You stay in control: it runs a **real, visible
browser** so you can log in, solve CAPTCHAs, and review before anything risky.

> ⚠️ **Read this first.** Indeed's Terms of Service prohibit automated bots, and
> Indeed uses anti-bot detection. Automating applications can get your account
> restricted. Use this on your own account, at your own risk, and keep an eye on
> what it does. This tool is deliberately *semi*-automated for that reason.

## How answers are resolved

For every application question, in order:

1. **Answer store** (`.secrets/answers_store.json`) — if you (or a past run) answered this
   or a near-identical question before, it's reused instantly. The store grows
   automatically every run, so over time fewer questions need the AI.
2. **Config answers** — the `answers:` and `profile:` blocks in `config.yaml`,
   keyword-matched to the question.
3. **Claude** — drafts an answer from your resume for anything unknown.

Answers from the store/config/profile are treated as *known* → eligible for
auto-submit. AI-drafted answers mark the job for **review** instead.

## Setup

```bash
# from S:\Programming\PythonProject
.venv\Scripts\activate           # or: python -m venv .venv first
pip install -r requirements.txt
python -m playwright install chromium

cp config.example.yaml config.yaml   # then edit config.yaml
setx ANTHROPIC_API_KEY "sk-ant-..."  # optional, for AI drafting (new shell after)
```

Put your resume at the path in `profile.resume_path` (PDF). For better AI answers,
also drop a plain-text `resume.txt` next to it — it's used to ground Claude.

## Run

```bash
python main.py            # search + apply per config.yaml mode
python main.py --dry-run  # just collect matching jobs, fill nothing
```

First run: the browser opens, you log into Indeed once. The login is saved to
`.browser_profile/` so later runs skip it.

## Modes (`behavior.mode` in config.yaml)

- `collect` — gather matching jobs to the summary only. Safest.
- `review`  — fill everything, then pause so you verify + submit each one.
- `auto`    — auto-submit applications (single **or** multi-page) whose answers are
  all *known* (store/config/profile). Jobs needing an AI-drafted answer follow
  `behavior.auto_submit_with_ai`: `false` flags them for review, `true` submits them too.

## When Indeed changes its page layout

Selectors are centralized in `src/indeed.py` → `SELECTORS`. If a step stops
working, update the matching entry there.

## Files

| File | Purpose |
|------|---------|
| `main.py` | entry point + run summary |
| `src/config.py` | load/validate `config.yaml` |
| `src/answer_store.py` | persistent Q→A store (check-first, grows over time) |
| `src/answers.py` | resolution engine: store → config → AI |
| `src/llm.py` | Claude answer drafting (model `claude-opus-4-8`) |
| `src/indeed.py` | Playwright search + apply flow |
