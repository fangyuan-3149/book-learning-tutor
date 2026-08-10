# T1 Smart Enrichment · Source Selection & Evaluation spec (read on demand)

A Book Learning Tutor course may be "good enough but not deep" or "partly outdated". T1 scans the course before opening and picks enrichment sources by the guide below — these are parallel options, not a priority order.

## Enrichment source selection

| Scenario | Which to use | Effect |
|------|--------|------|
| Concept outdated / needs frontier | arxiv (survey + classic + latest) | pull survey for the big picture, trace classics to the source, supplement the frontier |
| Programming / framework book | project-code analysis (target project) | reverse-engineer the capability-gap matrix from real code; everything learned is visible in the project |
| Needs authoritative confirmation | research / official docs / specs | ensure key concepts hold up |
| Backbone too thin | general tutorial / textbook search | supplement examples, supplement perspectives |

## Three-dimensional enrichment evaluation (importance / difficulty / time)

- **Importance**: ⭐⭐⭐ core (can't understand later without it) / ⭐⭐ important (practical but skippable) / ⭐ supplementary (optional).
- **Difficulty**: 🟢 easy (intuitive, has analogy) / 🟡 moderate (needs abstraction but understood once) / 🔴 hard (abstract + multi-step, must split).
- **Time**: estimated from `storage/习惯.md`'s `avg_time_per_concept` × number of concepts.

For lessons marked 🔴 hard or with low mastery history, decide in T1: how many sub-sections to split, how many examples to add, whether project-code cross-reference is needed.

## Time planning (fallback for standalone opening only)

When there is no course and the user directly says "help me learn X", give a plan by daily investment:
- Plan A 30min/day → about X days, master core + basic application
- Plan B 1h/day → about X days, master all + able to practice
- Plan C 2h/day → about X days, deep understanding + able to do projects
Total estimate = sum of per-chapter estimates; days = total estimate ÷ daily time.

## Enrichment landing (safe: unified single file)

**Only write `书库/<book>/_enrich.md` (one enrichment file per book); never modify the lesson bodies `第XX章_*/第XX课_*.md`.**

- Structure: under `# <book> 补强`, append by `## <chapter>/<lesson>` subsections, each with a source tag (arxiv / project-code / official docs) and distilled points.
- Reason: this skill has **no code guardrail** on lesson bodies; letting the agent edit `<lesson>.md` directly risks breaking the main course. Single-file isolation minimizes that risk.
- `progress.json` is unchanged; during teaching the lesson's enrichment is read by reference, not embedded in the lesson body.
