---
type: bugfix
date: 2026-11-17
title: "UXP session reads must validate every document identity"
files: ["photoshop/uxp-plugin/read-info.js", "photoshop/uxp-plugin/tests/read-info.test.js", "docs/uxp-1a-validation.md"]
tags: [bugfix, memory]
---

# UXP session reads must validate every document identity

## Tóm tắt
Session info now compares ordered open-document IDs after awaiting buildNumber and rejects stale results with a retry-read message.

## File liên quan
- `photoshop/uxp-plugin/read-info.js`
- `photoshop/uxp-plugin/tests/read-info.test.js`
- `docs/uxp-1a-validation.md`

## Bài học
- Checking only activeDocument identity misses inactive documents opening, closing, replacement, or reordering during an asynchronous session read. Snapshot and compare the complete ordered ID list, while retaining the active-document check. Identity checks do not provide an atomic snapshot of edits within an unchanged document.
