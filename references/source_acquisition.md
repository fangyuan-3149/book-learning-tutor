# Source Acquisition (optional · authorized)

This file is the full spec for SKILL.md's "Source Acquisition (optional · authorized)". The main path remains local files (`all-local`); this flow is enabled only when **the user has no local book AND explicitly authorizes** it.

## 0. When to enable

Enable only when ALL are met:

1. The user has not provided a local book path;
2. The user has not declared "local only";
3. The user has **explicitly authorized** online acquisition (granted permission to "find and fetch for me", ideally naming the book/author/edition).

If any is not met → use local `all-local`, no online access.

## 1. Autonomous flow

1. **Search candidates**: use the agent's own web search (WebSearch / WebFetch) by "title + author + edition/year" to find 1–3 public sources / book-page URLs.
2. **Confirm source (mandatory)**: list the candidates (site name, URL, scope to fetch: whole book or specific chapters) for the user; **fetch only after confirmation**. You may present multiple sources at once, but every actual fetch must fall within an already-confirmed scope.
3. **Fetch into `参考/<book>/`**: from a directory containing `tools/`, run —
   - One-shot: `python tools/acquire/pipeline.py all <keywords> [--idx N] [--max M]`
     - internally `search` → take first available result → `download` → `course_gen`, all the way to `书库/<book>/`.
   - List then fetch: `python tools/acquire/pipeline.py search <keywords>` lists available sources → `python tools/acquire/pipeline.py download <source> <bookURL> [book]` fetches a specific URL.
   - No existing source: `python tools/acquire/discover.py <bookURL>` auto-discovers a source definition and writes it to the local registry (`data/discovered/`), then `download`.
4. **Resume teaching**: once `参考/<book>/` is ready, proceed T0→T4 as usual (prep → Feynman → gate → review → homework → self-evolution).

## 2. Dependencies & boundaries

- **Full repo needed**: fetchers live in `tools/acquire/`, a repo-level capability. With only the bare skill installed (e.g. `~/.claude/skills/book-learning-tutor/`) there are no fetchers — the agent still searches and confirms, but hands the exact commands to the user to run inside the repo (or clones the full repo first).
- **Source registry `data/`**: structured book-site downloads depend on the **user-maintained** source registry (`data/active/` `data/discovered/` `data/imported/`, git-ignored, not shipped with the skill). An empty `data/` in the published repo is normal — sources are supplied by the user.
- **`config/backends.json`**: some sources/backends need user-supplied keys (git-ignored); when missing, only sources depending on that backend are affected, not general public-page fetching.
- **Copyright & compliance (user's sole responsibility)**: target only public sources the user **is authorized to access**; **do not bypass DRM / paywalls / login limits**; comply with local laws and platform ToS. Book-content copyright responsibility rests with the user (see `免责声明.md`).
- **Failure fallback**: if `search`/`all` find all sources unreachable it prints ✗ and prompts; then use the agent's own web search for public pages, if needed `discover.py` to build a source or `fetcher.py` to fetch a public page directly, then `download`/`ingest`; if still failing, ask the user for a local file.

## 3. Relationship to cross-host

This skill follows the Agent Skills open standard and is not bound to any host; but **online acquisition is a repo capability, not a bare-skill capability**. In any host (WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw), as long as that host's workspace has cloned the full repo (with `tools/acquire/`) and the user has authorized it, this flow can run.
