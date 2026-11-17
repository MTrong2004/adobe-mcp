# Premiere MCP — UXP, Premiere 26+

Python FastMCP stdio server using the root `core.client.BridgeClient('premiere')`, authenticated broker default `127.0.0.1:8768`, and official `require('premierepro')` UXP APIs. Installed Premiere26.0.1 is the target. No CEP dependency.

## Setup (manual plugin load required)

1. From repo root start broker: `python -m core.bridge --app premiere`. Keep it running. Its per-app token is `.runtime/premiere-token.txt`; copy it locally without putting it in chat/logs. Follow root setup scripts if available. Broker token file access is local; panel never stores token on disk.
2. Install **UXP Developer Tool 2.2+** through Creative Cloud Desktop if missing. This implementation does **not** claim to have installed/loaded the plugin programmatically.
3. Premiere → Settings → Plugins → Enable developer mode, restart Premiere.
4. UXP Developer Tool → **Add Plugin** → choose `premiere/uxp-plugin/manifest.json` → **Load**. Panel: Window → UXP Plugins → Premiere MCP. Manifest changes require Unload/Load.
5. Enter broker token in password field, click **Kết nối**. Keep panel/session open until pending results are acknowledged. Token remains only in panel memory; reload requires reentry. Never reload to retry an operation whose outcome is unknown.
6. MCP client command: `uv run "C:/Users/trong/VS Code/adobe-mcp/premiere/server.py"` (PEP723 installs pinned `mcp==1.30.0`). Use absolute path; stdio only. Broker is separate.

Plugin requests only loopback8768 and full filesystem access for file readback. It does not depend on browser CORS; UXP network permission controls fetch. Do not replace it with a browser web page. Full filesystem permission is required for native import/export/save paths and verification. UI uses plain text rendering and CSS color tokens.

## Tools

- `premiere_health`: broker health, plugin connection, busy/unknown state and last receipt.
- `premiere_session_info`: read-only UXP capabilities and active-project presence.
- `premiere_project_info`: project, recursive items (max10000), actual `getId()` strings, media paths, sequence GUIDs/tracks/duration.
- `premiere_import_media(paths, bin_name?)`: absolute existing sources; named root bin reused or created transactionally; new item IDs and source paths verified. Partial imports return structured failure plus verified imported items. Do not automatically retry.
- `premiere_create_sequence(name,item_node_ids)`: nonempty media clip IDs from inventory/import; official createSequenceFromMedia. New sequence GUID/name checked.
- `premiere_insert_clip(sequence_id,project_item_id,track_type,track_index,time_seconds,companion_track_index?)`: zero-based **existing** destination tracks, ripple insert with limitShift true. Mixed AV requires explicit opposite stream companion index; no silent audio insertion/undocumented negative-index suppression. Single-stream source uses primary track. Verifies source ID/start-time increase on each destination. Timeline may snap to frames; readback tolerance0.05sec. Track creation and stream-only extraction from mixed media are unsupported.
- `premiere_export_sequence(sequence_id,output_path,preset_path)`: existing `.epr` preset, new absolute output. Uses IMMEDIATELY (25.6 API), no AME launch or26.3 queue calls. Returns success only after API returns true and a nonempty output exists. Does not decode/check media integrity; inspect output before production delivery. Long exports can outlive300sec broker deadline; check host/output/late receipt instead of resubmitting.
- `premiere_save_project(path,overwrite=False)`: Save As; new copy becomes active. Explicit overwrite opt-in for existing file. Checks active path and nonempty disk file. Readback checks do not eliminate external filesystem races.

All errors use `{success:false,error:{code,message},outcome_unknown?:boolean}`. Requests serialize; expiry uses Unix epoch **seconds**. Received job IDs are never executed twice in a panel session. A result is retained in memory until authenticated POST acknowledgment; network retries send only the receipt. No persistence of pending receipts across UXP reload/application crash: broker preserves uncertain job state; manually reconcile with app/output/health before any retry. Stop receiving does not cancel a running host operation.

## Verification

`node --test premiere/tests/*.test.js`

`uv run premiere/test_server.py` (SDK stdio handshake/list-tools; no live Premiere mutation).

Mocks follow the real official API shapes, and are **not live verification**. Loading through UDT and exercising real project/import/insert/export/save is a separate manual acceptance step. Read [API notes](API-NOTES.md) for sources, version gates, and limitations. No claim of production live acceptance until those host checks pass.
