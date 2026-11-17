---
type: decision
date: 2026-11-17
title: "Adobe mutations must not replay after timeout or disconnect"
files: ["photoshop/server.py", "photoshop/test_server_runtime.py"]
tags: [decision, memory]
---

# Adobe mutations must not replay after timeout or disconnect

## Tóm tắt
Photoshop COM scripts remain on one worker after caller timeout; queued/new dispatch is gated while prior call runs. A disconnect after DoJavaScript dispatch reports outcome_unknown and never replays the submitted JSX.

## File liên quan
- `photoshop/server.py`
- `photoshop/test_server_runtime.py`

## Quyết định
- Use a single owning COM worker and retain running futures; timeout cancels waiting, not Adobe execution. Read state before submitting a new mutation.

## Bài học
- An asyncio timeout or cancellation does not stop an in-flight COM operation. Creating a replacement executor can overlap document mutations; disconnect may occur after the change was applied.
