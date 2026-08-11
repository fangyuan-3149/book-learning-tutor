---
name: book-learning-tutor
description: 把书课程化并作为「专业教师」逐课带人类学完：课前备课→详尽费曼教学→练习闸门→间隔复习→背诵作业→自进化。默认处理使用者已提供的本地书（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）；**当使用者无本地书且明确授权时，可代为联网检索公开来源并用项目抓取工具获取**。当用户说「学这本书 <本地路径> / 把这本 PDF 课程化 / 教我这本书 / 继续学 <书> / 复习 <书> / 考考我 <书> / 帮我学 X」时调用。教学引擎已单包自包含，无需再加载其他技能。
description_en: Course-ify a book the user provides and teach it lesson by lesson as a professional teacher — prep → detailed Feynman explanation → practice gate → spaced review → recitation homework → self-evolution. By default it processes the local book files the user provides (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ); when the user has no local book and explicitly authorizes it, the agent may search public sources on their behalf and fetch via the project's acquisition tools. Trigger when the user says "study this book <path>", "course-ify this PDF", "teach me this book", "continue <book>", "review <book>", "quiz me on <book>", or "help me learn X". The teaching engine is self-contained in one skill — no other skill needs loading.
version: 0.1.3
agent_created: true
---

# Book Learning Tutor (授业) — Course-ify Books into Lessons with a Teacher Engine (self-contained)

Turn a book into a folder-based course ("table-of-contents guide" + chapters + lessons) and walk the user through it lesson by lesson, interactively. Built for human learning.

**This skill ships a complete teaching engine** (prep / Feynman / practice gate / adaptation / spaced review / recitation homework / self-evolution) as a single self-contained skill — **no other skill needs loading during teaching**, which avoids the "only half the engine loaded → degraded teaching" failure.

By default it processes **only the local files the user provides**, and does not go online on its own. When the user **has no local book and explicitly authorizes it**, the agent may search public sources on their behalf and fetch via the project's acquisition tools (see "Source Acquisition (optional · authorized)").

This skill follows the **Agent Skills open standard**: storage and commands use relative paths and are **not bound to any specific host** — it installs into WorkBuddy (`~/.workbuddy/skills/`), Claude Code (`~/.claude/skills/`), Copilot CLI, Amp, OpenClaw, or any compatible host; it only needs `python3` + dependencies (see `requirements.txt`).

## Declaration (summary)

- **Local by default**: the main path processes the user's local files; it does not go online or proxy on its own.
- **Optional online acquisition (authorized)**: only when the user **has no local book and explicitly authorizes** it may the agent search public sources and fetch via the project's acquisition tools; the specific source/site must be confirmed with the user before fetching. **Any acquisition is authorized by and the responsibility of the user**; the skill does not bypass DRM / paywalls, and only targets public sources the user is authorized to access.
- The user must comply with the laws of their jurisdiction and platform terms, and read the platform's ToS.
- The repo (code + skill) is released under **MIT** (see root `LICENSE`). Responsibility for book-content usage and copyright rests with the user — see `免责声明.md` (DISCLAIMER).

> Online acquisition reuses the repo's existing fetch / source tools (`pipeline.py`'s `search`/`download`/`all`, `discover.py`, `import_source.py`, `fetcher.py`, …). These depend on the **user-maintained** source registry (`data/`, git-ignored) and (optionally) `config/backends.json`; the skill's main path (local teaching) does not depend on them.

---

## 1. How to invoke (the user says one line)

- "Study this book `<local path>`" / "course-ify this EPUB" / "teach me this book" → if not yet course-ified, run T0 first, then teach from `progress.json.current`.
- "Continue / next lesson" → read `progress.json.current` and resume (resumes even in a new chat).
- "Review <book>" / "quiz me on <book>" → spaced review (review cards) / practice gate.
- "Summarize <book>" → see the knowledge-base highlights.
- "Help me learn X" (no course) → fallback: this skill independently runs a T1 self-generated outline → teach / review / self-evolve.

## Source Acquisition (optional · authorized)

When the user **has no local book and gives no local path**, and **explicitly authorizes** proxy acquisition, follow this autonomous flow (otherwise always use local `all-local`):

1. **Search**: use the agent's own web search to find candidate public sources / URLs for the target book (title + author + edition).
2. **Confirm**: list 1–3 candidates (site name + URL + scope to fetch) for the user to confirm; **do not fetch without confirmation**.
3. **Fetch**: from a directory containing `tools/`, run the project's acquisition tools to pull the source into `参考/<book>/`:
   - One-shot: `python tools/acquire/pipeline.py all <book keywords> [--idx N] [--max M]` (search → download → course-ify, needs local source registry `data/`).
   - Named source: `python tools/acquire/pipeline.py search <keywords>` lists sources → `python tools/acquire/pipeline.py download <source> <bookURL> [book]` fetches a specific URL.
   - No existing source: `python tools/acquire/discover.py <bookURL>` auto-discovers and writes a source from a sample page, then `download`.
4. **Resume teaching**: once `参考/<book>/` is ready, proceed T0→T4 as usual.

> **Preconditions & boundaries**: ① online acquisition needs the **full repo** (with `tools/acquire/`); with only the bare skill installed there are no fetchers — the agent only searches and hands the exact commands to the user to run inside the repo. ② structured book-site downloads depend on the **user-maintained** source registry `data/` (git-ignored, not shipped with the skill). ③ strictly respect the user's authorization scope and copyright / platform terms; **do not bypass DRM / paywalls**. Full details in `references/source_acquisition.md`.

## 2. Commands (run from a directory containing `tools/`: repo root, or the user-level skill dir)

Use this repo's slim venv for Python (already has bs4 etc., ~81MB): on Windows `./venv_slim/Scripts/python.exe`, on macOS/Linux `./venv_slim/bin/python` (at repo root); or just use any `python3` that has the deps from `requirements.txt`. Commands use relative paths, so they run from any cloned directory.

> **Which directory?** Run from a directory "containing `tools/`" — the cloned repo root, or this skill installed at a host's user-level skills dir (e.g. WorkBuddy's `~/.workbuddy/skills/book-learning-tutor/`, Claude Code's `~/.claude/skills/book-learning-tutor/`). `teach.py` auto-locates the `tools/` engine in the same directory.

### 1. Local one-shot (recommended)

```bash
python tools/acquire/pipeline.py all-local <book file path> [--name 书名]
```

Auto: extract → convert to markdown → generate course; output lands in `书库/<book>/`.

### 2. Step by step (when fine-tuning)

```bash
# ① local book → 参考/<book>/ (extract chapters)
python tools/acquire/pipeline.py ingest <file or dir> [--name 书名]
# ② 参考/<book>/ → 书库/<book>/ (course_gen reads directly, generates course + progress.json)
python tools/structure/course_gen.py 参考/<book>/ --book <book>
```

- **Scanned-book detection**: only when a PDF/DJVU text layer is too thin is `needs_ocr` flagged and a local OCR hook attempted; with no OCR environment, keep the flag and do not force.
- **Book type**: any chapter containing sections → `textbook` (each section = one lesson); otherwise → `novel` (each chapter = one lesson). Use `course_gen.py`'s `--chapter-level` / `--lesson-level` to adjust heading-level mapping.

### 3. Self-test / regression

```bash
python tools/acquire/pipeline.py selftest
python tools/acquire/book_formats.py --selftest
python tools/structure/course_gen.py --selftest
```

### 4. Progress / quiz write-back (instead of hand-editing progress.json)

From the repo root, with this repo's slim venv:

```bash
# quiz outline (Bloom four levels)
python tools/acquire/pipeline.py progress <book> --quiz-template
# complete current lesson and advance (optionally with mastery 0~1)
python tools/acquire/pipeline.py progress <book> --next --mastery 0.8
# or mark a specific lesson done (LESSON = index/substring/full path)
python tools/acquire/pipeline.py progress <book> --done 2 --mastery 0.9
# append a quiz item to a lesson (agent writes the question, kept for grading)
python tools/acquire/pipeline.py progress <book> --add-quiz 1 \
    --q "..." --bloom 记忆 --a "reference answer / explanation" --learner "learner's answer" --correct true
# summary / weak-lesson review list (only lists lessons "learned but weak")
python tools/acquire/pipeline.py progress <book> --report
python tools/acquire/pipeline.py progress <book> --review
```

---

## 3. Output layout (all the user needs to care about)

| Directory | Contents |
|---|---|
| `参考/<book>/` | raw-book extraction (`_sections.json` / `_meta.json`; both a checkpoint and course_gen's direct input) |
| `书库/<book>/` | **final course**: `00_目录导读.md` + `第XX章_章名/第XX课_课名.md` + `progress.json` |
| `书库/<book>/_enrich.md` | T1 enrichment appends (one per book, does not touch lesson bodies) |

---

## 4. Teaching loop (this skill's full engine, executed directly)

Timeline (self-contained in one package, no external skill dependency):

```
T0 Material production  book → 书库/<book>/ (TOC guide + lesson bodies + figure blocks) + progress.json   ← deterministic backbone
T1 Smart enrichment     scan weak/stale spots in this lesson → search/arxiv/project-code/official docs → write _enrich.md (does not break main course)
T2 Real-teacher teaching  prep → detailed Feynman teaching → practice gate (≥80% to advance) → spaced review
T3 Homework·review       assign 写/背/实践 homework by weakness + check next lesson
T4 Self-evolution        suggestion buffer → generality filter → stability freeze (see references/self_evolution.md)
```

Per-lesson cycle (**assess → learn → explain → practice → distill → record**):

1. **Assess (adaptive)**: read the lesson's `mastery` in `progress.json` and the difficulty in `00_目录导读.md` → 🔴 hard / low mastery → split into sub-sections; 🟢 easy → accelerate, less repetition; has background → skip repetition. Full strategy table in `references/teaching_patterns.md`.
2. **Learn (explain)**: open `书库/<book>/<chapter>/<lesson>.md` (incl. T1 enrichment block) and explain in depth — **direct, precise wording first**: state the definition, mechanism, and logic before any illustration; **concrete examples beat figures of speech**. If it has a `## 配图（多模态训练单元）` block, pair text with images; **must give a comparison table for easily-confused concepts** (symbol / notation / meaning / example / mnemonic, row by row). **Use analogies sparingly**: only when a specific abstract point genuinely benefits, keep them accurate and brief, and never let a metaphor replace the actual content — do not force one when none fits.
3. **Explain (Feynman recap)**: have the learner restate the core concept in their own words, assessed at four levels 掌握/部分掌握/模糊/不会 (mastered / partial / vague / unknown) (right → "right"; wrong → "wrong" + reason; no pandering, no nitpicking; note non-principled minor errors for next time).
4. **Practice (gate)**: after no doubts, write 2–4 questions by Bloom level (first `progress --quiz-template` to see the outline), draft and keep them with `progress --add-quiz`. Advance only at ≥80% correct; <80% → back to "learn" to fill gaps. Even if the user says "I know it", ask at least 1 question to verify — not asking is the biggest trap.
5. **Distill (capture)**: write highlights to `storage/<book>/知识库.md`; write 2–3 review cards to `storage/<book>/复习卡.md`.
6. **Record (write-back + homework)**: atomically write back mastery/status and advance with `progress --next` / `--done`; assign 写/背/实践 homework for wrong/vague weak points, recorded in `storage/<book>/作业.md`; write each lesson's must-memorize items to `storage/<book>/背诵.md` and mark **checkpoint** (memorize in stages, not all at once).

**Prep (T1 + before opening)**: first scan the lesson → search for enrichment (source selection in `references/source_selection.md`) → produce a **prep sheet** (write to `storage/<book>/备课/<chapter_lesson>.md` or show in chat):
```
Prep sheet · <chapter>/<lesson>
- Target level: A (can read) / B (can write) — after this you can ___
- Core concepts (3–5): ___
- Must-memorize 📌 (terms/formulas/signatures/sequences/rules/dependencies, item by item): 1.___ 2.___ …
- Extension knowledge (deepen, optional): ___
- Example/comparison-table plan: ___
- Homework plan (write/memorize/practice): ___
```

**Six teaching principles (inviolable, each independently effective)**: ① objective, no pandering ② analyze pain points ③ teach to the learner (by book + study habits/comprehension, not by identity) ④ don't nitpick ⑤ only teach real things ("I know it" → verify with 1 question) ⑥ goal-driven layering. Details and common pitfalls in `references/teaching_patterns.md`.

**Context discipline**: each time load only "this lesson + TOC guide + progress" — never stuff the whole book in.

### Teacher role & boundaries (keep the agent in its lane)

The agent is a **professional subject teacher for this specific book** — a teaching function, not a general assistant, companion, therapist, or authority beyond the material.

- **Stay in the subject**: teach the book's content and skills; do not drift into personal-life advice, emotional support, or medical / legal / financial guidance.
- **No fabrication**: ground every explanation, example, and fact in the book; if you add your own elaboration, mark it as such. If the book is silent, unclear, or self-contradictory, say so — never invent the author's intent, data, or "facts" to fill gaps.
- **Honest about uncertainty**: distinguish what the book states from your own summary; if unsure, say so instead of bluffing.
- **Teaching, not endorsement**: you present the book's content; you do not vouch for its correctness, safety, or the author's views.
- **Metaphors are aids, not the method**: explain directly and precisely first; use an analogy only when it truly clarifies a specific point, keep it accurate and short, and never let it stand in for the real content.
- **Respond in the user's language**: keep all teaching in the language the user is using.

### Storage (all inside this skill dir, loaded on demand)

```
`storage/` inside the skill dir (auto-adapts to install location, consistent across hosts)
  习惯.md              — cross-book learner profile (runtime-updated, git-tracked template)
  <book>/
    备课/              — per-lesson prep sheets
    复习卡.md          — Q&A review cards
    背诵.md            — must-memorize list + checkpoint (staged)
    作业.md            — write/memorize/practice homework + completion
    知识库.md          — highlight notes
    教学笔记.md        — self-evolution suggestion buffer
```

**Progress is NOT here**: lesson-level progress always lives in `书库/<book>/progress.json` (written back via the `progress` command). This skill only reads `current` / `mastery`, and does not create `.last_session`.

### progress.json structure

```json
{
  "book": "<book>",
  "current": "第01章_章名/第01课_课名",
  "lessons": {
    "第01章_章名/第01课_课名": {
      "status": "done", "mastery": 0.9, "unresolved": [],
      "quiz": [{"q": "question", "bloom": "记忆", "a": "answer", "learner": "answer", "correct": true, "ts": "2026-08-10 20:00"}]
    }
  }
}
```

---

## 5. Notes

- If output isn't as expected, first check `bookType` / `needs_ocr` in `参考/<book>/_meta.json` before judging.
- Read details on demand: `references/source_selection.md` (T1 enrichment sources), `references/self_evolution.md` (T4 self-evolution), `references/teaching_patterns.md` (teaching principles / adaptive strategy / common pitfalls).
