---
type: lesson
date: 2026-11-17
title: "Premiere UXP API baseline must match installed host version"
files: ["premiere/uxp-plugin/main.js", "premiere/uxp-plugin/dispatcher.js"]
tags: [lesson, memory]
---

# Premiere UXP API baseline must match installed host version

## Tóm tắt
Premiere26 uses UXP with synchronous properties and some methods such as ProjectItem.getId, asynchronous host operations, and lockedAccess executeTransaction for actions. Shared UXP filesystem exposes fs.lstat Promise rather than Node fs.promises.stat.

## File liên quan
- `premiere/uxp-plugin/main.js`
- `premiere/uxp-plugin/dispatcher.js`

## Bài học
- Validate API signatures against official versioned documentation and injected entrypoint tests. Latest samples can use newer host APIs; mixed audio/video insertion needs explicit destination indices for both streams.
