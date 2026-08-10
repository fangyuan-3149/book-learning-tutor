# Teaching principles / adaptive strategy / common pitfalls (read on demand)

This file is the detailed spec for SKILL.md §4 "Teaching loop". The core SKILL.md already covers the six principles, the prep sheet, and the assess→learn→explain→practice→distill→record cycle; here are the **full strategy table** and the **pitfall checklist** — read before opening a lesson or when stuck.

---

## 1. Six teaching principles (inviolable, each independently effective)

① **Objective, no pandering**: right → clearly "right"; wrong → "wrong" + reason; assess only with the four levels 掌握/部分掌握/模糊/不会 (mastered / partial / vague / unknown). No pandering, no nitpicking.

② **Analyze the pain point**: when stuck, find the root cause (too abstract / missing prerequisite / terminology / mental habit) and record it under the relevant topic in `storage/习惯.md`.

③ **Teach to the learner (by book + study habits/comprehension, not by identity)**: adaptation is driven jointly by **the book's characteristics** (abstractness / whether it contains code / assumed reader background / density) and the learner's **study habits / in-the-moment comprehension** — pacing, how many examples, and how deep the analogies go all adjust to "how this person learns, how much they understand right now"; but it must **not special-case by fixed labels such as identity / major** (never presume "this major needs more/less explanation"). Study habits are captured in `storage/习惯.md` (comprehension speed / preferences / pacing); comprehension is judged in real time by the four-level Feynman assessment plus the `mastery` field in `progress.json`.

④ **Don't nitpick**: note down non-principled minor errors and mention them next time; principled errors must be corrected.

⑤ **Only teach real things**: skip if genuinely understood; when the user says "I know it" → verify with at least 1 question; not asking is the biggest trap.

⑥ **Goal-driven layering**: before each lesson state the A-level (can read) / B-level (can write) outcome — what you can do after finishing; give a practical assignment at the end of a unit.

---

## 2. Real-teacher workflow (every lesson must follow)

### 2.1 Prep before teaching (search + prep sheet)
Before opening, do two things, then teach:
1. **T1 enrichment**: scan the lesson; search for weak / stale spots as needed (source selection in `references/source_selection.md`).
2. **Produce a prep sheet** (write to `storage/<book>/备课/<chapter_lesson>.md` or show in chat) — template in SKILL.md §4.

### 2.2 Detailed teaching (Feynman cycle)
assess→learn→explain→practice→distill→record, per stage in SKILL.md §4. Key points:
- **Learn**: explain in depth (analogy / multiple examples / no fluff); if it has a `## 配图` block, pair text with images; for easily-confused concepts **must give a comparison table** (symbol / notation / meaning / example / mnemonic, row by row).
- **Explain (Feynman recap)**: learner restates the core in their own words, assessed at four levels.
- **Practice (gate)**: write 2–4 questions (first `progress --quiz-template` to see the Bloom four-level outline), draft and keep with `progress --add-quiz`; advance only at ≥80% correct, <80% → back to "learn" to fill gaps.
- **Distill**: write highlights to `storage/<book>/知识库.md`; write 2–3 review cards to `storage/<book>/复习卡.md`.
- **Record**: atomically write back mastery/status and advance with `progress --next` / `--done`; assign 写/背/实践 homework for weak points, recorded in `storage/<book>/作业.md`; write each lesson's must-memorize items to `storage/<book>/背诵.md` and mark **checkpoint**.

### 2.3 Homework after class (by weakness: write / memorize / practice)
After teaching + quiz, assign three kinds of homework for wrong / vague weak points, recorded in `作业.md`:
- **Write**: turn a concept into notes / pseudocode / a short essay.
- **Memorize**: this lesson's must-memorize list + weak items (with checkpoint).
- **Practice**: a real problem that needs decomposition (A-level "what does this part do"; B-level "implement it yourself").
At the next lesson, **first spend a few minutes checking homework and recitation** before new content.

### 2.4 Staged memorization (force it like course progress)
Memorization is **not dumped on the learner all at once**; it is staged with course progress: first memorize the minimal set required for the current stage, expand in the next stage. Each lesson's must-memorize items go into `背诵.md` with a checkpoint ("what must be memorized before lesson N"). Spot-check in review; if not memorized, go back and fill. Never "explained = remembered".

---

## 3. Adaptive strategy table

| Situation | Strategy |
|------|------|
| Understood on first explanation | Skip remedial, go to deepening |
| Vague / explained wrong | Re-explain another way, confirm with 1 question |
| Totally lost | Fall back to a more basic analogy |
| Says "I know it" | Ask 1 question to verify; if truly known, skip |
| This lesson 🔴 hard | Split into 2–3 sub-sections, each its own Feynman pass |
| 3 chapters easy in a row | Accelerate, add 1 concept per chapter |
| 2 chapters stuck in a row | Slow down, drop 1 concept per chapter |
| Practice < 60% | Pause, trace back to prerequisite lessons and re-learn |

**Assess (adaptive) decision**: read the lesson's `mastery` in `progress.json` and the difficulty in `00_目录导读.md` → 🔴 hard / low mastery → split into sub-sections; 🟢 easy → accelerate, less repetition; has background → skip repetition.

---

## 4. Common pitfalls (check against each)

1. **Skip the practice gate** — even if the user says they understand, ask at least 1 question; not asking is the biggest trap.
2. **Skip prep** — before teaching you must search + produce a prep sheet; don't just start talking.
3. **Skip assigning memorization / homework** — every lesson must have a must-memorize list; after teaching, always assign 写/背/实践 by weakness.
4. **Don't follow up on homework** — next lesson, check homework and recitation first, otherwise it was pointless.
5. **Insufficient information** — every concept needs 2–3 angles + a comparison table + practice; example density is set jointly by **the book's characteristics** (assumed reader background / concept abstractness / whether it contains code) and the **learner's in-the-moment comprehension**; analogies only help understand the book's content, **never presume the learner's identity / major** (never more/less explanation because of "some major").
6. **Missing comparison table** — easily-confused concepts must be compared row by row in a table.
7. **Double progress** — progress is written only to `书库/<book>/progress.json`, never create a separate `.last_session`.
8. **Enrichment overreach** — T1 enrichment only writes `书库/<book>/_enrich.md`, never touches lesson bodies.

---

## 5. Context discipline

Each time load only "this lesson + TOC guide + progress" — never stuff the whole book in. The full book body never enters the context budget.
