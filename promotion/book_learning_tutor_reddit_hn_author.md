**Book Learning Tutor（授业）—— Author Introduction**

I built this tool because I kept buying books, highlighting them, and forgetting them. Reading wasn’t learning.

I didn’t want another “local PDF chatbot”. I wanted a **real AI teacher** that explains like a teacher, uses Feynman-style teaching, practice gates, and actually makes you understand before moving on.

### Core design philosophy (the things I refused to compromise on)

- **Local-first & private** — the book never leaves your machine
- **No external LLM key** for the teaching path — intelligence comes from the agent host; tools do deterministic work (parse, course-ify, progress write-back)
- **Single self-contained skill** — full teaching engine in one package, so teaching doesn’t degrade when only half a stack is loaded
- **Cross-host** — WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw style skill installs
- **No book content in the repo** — you bring the files; responsibility stays with the user

I built this first for myself. If it’s good, I’m shipping it. I hope it helps people who own books but don’t finish them.

Repo: https://github.com/fangyuan-3149/book-learning-tutor

Example: `examples/flatland/` contains a complete TOC guide + Lesson 1 for *Flatland* (public domain), so you can see the lesson shape without installing anything.

Feedback welcome:
- Is the ≥80% mastery gate too strict or just right?
- What’s the worst book format you’ve tried locally?
- What feature do you most want to see added?

