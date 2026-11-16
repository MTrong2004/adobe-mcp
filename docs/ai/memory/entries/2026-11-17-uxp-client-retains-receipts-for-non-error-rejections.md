---
type: bugfix
date: 2026-11-17
title: "UXP client retains receipts for non-Error rejections"
files: ["photoshop/uxp-plugin/client.js", "photoshop/uxp-plugin/tests/plugin.test.js"]
tags: [bugfix, memory]
---

# UXP client retains receipts for non-Error rejections

## Tóm tắt
Normalize dispatch rejection values before building the receipt and guard transport status access. Previously null or undefined dispatch rejections caused a second TypeError, lost the receipt and left the broker waiting for a claimed job.

## File liên quan
- `photoshop/uxp-plugin/client.js`
- `photoshop/uxp-plugin/tests/plugin.test.js`

## Bài học
- JavaScript promise rejection values need not be Error objects. Error handling at job execution boundaries must tolerate null and undefined so it still records and delivers a failure receipt without replaying the operation.
