---
type: decision
date: 2026-11-17
title: "Monorepo adobe-mcp, one MCP server per app"
files: ["AGENTS.md"]
tags: [decision, memory]
---

# Monorepo adobe-mcp, one MCP server per app

## Tóm tắt
Repo holds photoshop/ (and later other Adobe apps) plus core/ for shared code; each app is a separate MCP server.

## File liên quan
- `AGENTS.md`

## Quyết định
- One repo, separate servers so agents only load the app they need; extract core/ only when a second app exists. COM/ExtendScript stays default until UXP tools are verified in real Photoshop (see photoshop/UXP-ROADMAP.md).
