---
type: lesson
date: 2026-11-17
title: "Photoshop distort via Action Manager silently ignores wrong formats"
files: [".gitignore", "AGENTS.md", "CLAUDE.md", "GEMINI.md"]
tags: [lesson, memory]
---

# Photoshop distort via Action Manager silently ignores wrong formats

## Tóm tắt
4-corner distort only works with Trnf + rectangle (L,T,R,B #Pxl) + quadrilateral (8 #Pxl TL,TR,BR,BL).

## File liên quan
- `.gitignore`
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`

## Bài học
- nonAffineTransform, quadCorners and Pnt lists are silently ignored without error; always re-read layer bounds after any transform. Large images can hang Photoshop when switching to AI Assisted mode.
