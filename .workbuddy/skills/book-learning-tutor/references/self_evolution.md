# T4 Improvement · Self-evolution spec (read on demand)

Keeps the full methodology (suggestion buffer → generality filter → stability marker → decision tree). **Consistent across hosts**: this skill does not rely on any host-specific skill write-back tool; suggestions that pass the generality check are left in `storage/<book>/教学笔记.md`, and the user / agent manually vets them before hardening into SKILL.md (see the "Acquisition pipeline / self-evolution" section of this repo's `README.md`).

## 1. Suggestion collection (buffer)
During teaching, spot improvable points → record in `storage/<book>/教学笔记.md`. Example: user reacts "analogies are easier to understand" → suggest using more analogies; user forgot yesterday's content → suggest adding a 3-minute review before each new lesson.

## 2. Generality filter (3 questions)
① Only effective for the current user, or effective for most learners? → only current → write to `storage/习惯.md`; most learners → next step.
② Holds across 3 different chapters/topics? → yes → next step; no → keep observing (mark "observing").
③ Conflicts with an existing rule? → no conflict → write to SKILL.md; conflict → merge/replace the old rule.

## 3. Stability marker
🆕 new → ⏳ observing (use 1–2 times) → ✅ stable (effective 3 times in a row) → 🔒 no change needed (no modification 5 times in a row).
A rule effective 3 times in a row → mark ✅; no new suggestion 5 times in a row → mark 🔒, unless the user asks to stop changing.

## 4. Decision tree
Ignore transient issues; reusable → buffer → observe → generality check → write SKILL.md / write 习惯.md → mark → stable / frozen.

## 5. Knowledge-base auto-maintenance (must do at session end)
1. Update progress (skip if progress.json already written back).
2. Learned a new function/method → append the corresponding entry to `storage/<book>/背诵.md` (mark 📌/📖).
3. Update `storage/<book>/复习卡.md` (if new cards).
4. Update `storage/习惯.md` (actual time spent / comprehension speed / preferences / pacing).
5. Cross-session: `progress.json.current` is the resume position; no separate file needed.
