---
type: lesson
date: 2026-11-17
title: "Never commit agent review logs to this public repo"
files: [".gitignore", "AGENTS.md", "CLAUDE.md", "GEMINI.md"]
tags: [lesson, memory]
---

# Never commit agent review logs to this public repo

## Tóm tắt
A Copilot review log (uxp-1a-review.md) with an M365 account email and chat URL was pushed by git add -A and had to be purged from master history.

## File liên quan
- `.gitignore`
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`

## Bài học
- Repo is public: check git status for untracked agent/Copilot logs before git add -A; *-review.md and bridge-token.txt are gitignored. Never put tokens, account emails or chat links in memory entries.
