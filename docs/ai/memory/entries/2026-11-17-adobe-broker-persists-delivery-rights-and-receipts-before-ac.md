---
type: decision
date: 2026-11-17
title: "Adobe broker persists delivery rights and receipts before acknowledgment"
files: ["core/bridge.py", "core/client.py"]
tags: [decision, memory]
---

# Adobe broker persists delivery rights and receipts before acknowledgment

## Tóm tắt
AE and Premiere use separate authenticated loopback brokers and fixed operation dispatchers. Claimed jobs are journaled before delivery; restart preserves uncertain outcomes and duplicate result submission is acknowledged without replay.

## File liên quan
- `core/bridge.py`
- `core/client.py`

## Quyết định
- Keep one panel per app, per-app token and single in-flight job. Preserve claimed unknown work across broker restart; reconcile with matching late result or explicit human inspection.

## Bài học
- A lost result acknowledgment is not evidence that Adobe did not run the operation. Retry only the identical receipt; never re-execute a mutation to repair transport.
