# Optional Photoshop UXP panel

This plugin is **opt-in and not host-verified yet**. Keep COM as the default backend. Do not enable UXP for normal MCP use until the manual Photoshop checks below pass. Loading the panel does not connect automatically; the user must enter a token and click **Kết nối**.

Requires Photoshop 25.10 or later and Adobe UXP Developer Tool. The panel communicates with a standalone Python HTTP bridge, which runs separately from the MCP process.

## Load for a controlled host test

1. Enable Photoshop **Preferences > Plugins > Enable Developer Mode** and restart if prompted.
2. In UXP Developer Tool choose **Add Plugin** and select `C:/Users/trong/VS Code/photoshop-mcp/uxp-plugin/manifest.json`, then **Load**.
3. Open the **AI Kit Bridge** panel from Photoshop's Plugins menu or UXP Developer Tool.
4. Start the standalone Python bridge using the repository instructions. Enter the same token as `PS_UXP_TOKEN`, or the generated token displayed by the bridge if that variable is unset. Click **Kết nối**.
5. Keep exactly one panel client connected. **Ngắt kết nối**, panel hide/destroy, or plugin unload stops new polling and clears the token. An operation already executing may finish; its unsent result remains in memory for reconnecting.

No token logging or persistence is implemented. The input is cleared immediately on connection attempt. HTTP requests already sent may retain authorization until they settle. No arbitrary JavaScript, filesystem access, save, delete, or document-close operation is exposed.

## Protocol 1

The only allowed origin is `http://127.0.0.1:8766`. Every request carries `Authorization: Bearer <token>`.

- `GET /health`: requires `{ "success": true, "protocol": 1 }` before polling.
- `GET /next`: immediate response `{ "job": null }` or `{ "job": { "id": "unique-string", "operation": "...", "args": {}, "expires_at": 1790000000000 } }`.
- `POST /result`: `{ "id": "...", "result": { "success": true, ... } }` or `{ "id": "...", "error": "message" }`. Acknowledgement must include `{ "success": true }`.

Polling is sequential, scheduled 500 ms after the previous request/execution/result finishes. XHR timeout is 5 seconds. Failed result delivery retries only the retained result, never the operation, and blocks fetching another job until acknowledgement. In-memory receipts prevent repeating previously seen IDs while the plugin stays loaded. The bridge must never reuse job IDs or requeue delivered jobs. No long polling.

HTTP 4xx stops the connection, including stale-result HTTP 400 after bridge restart. If the restarted bridge cannot accept a pending receipt, unload/reload the plugin to clear that receipt, reconnect, and inspect the document before submitting another mutation. Never automatically resubmit an uncertain mutation. Reloading clears the in-memory replay guard.

Expired jobs are rejected before execution, inside `executeAsModal`, and after history suspension. Document/layer IDs are re-resolved inside modal execution. Closed documents and removed layers cannot redirect mutations to the active document. A job targeting another still-open document edits that explicit document.

## Operations

- `session_info`, args `{}`: `{success:true,version,active_document_id,documents:[{id,name}]}`. Active ID is null when there are no open documents.
- `document_info`, args `{document_id?,include_layers?:true,max_depth?:-1}`: `{success:true,document:{id,name,width,height,resolution,mode,layers?}}`. Width/height come directly from the UXP DOM in pixels; resolution is pixels/inch. Root layers have depth 0; `max_depth:0` includes roots only; `-1` traverses all descendants. Groups have `children` and `children_truncated`; layers expose `id,name,visible,opacity,kind`. `include_layers:false` omits the tree.
- `update_layer`: required positive integer `document_id` and `layer_id`; at least one of `name`, `visible`, `opacity`. Name must be 1–255 characters, not whitespace-only, and contain no control characters. Visible must be boolean; opacity must be finite, from 0 to 100. Returns `{success:true,document_id,layer:{id,name,visible,opacity,kind}}`.

Unknown operations and arguments fail validation. Mutations use `executeAsModal`, a one-second host lock timeout, and one suspended history state. Property-write or result-read failures call `resumeHistory(suspension,false)` to roll back. If explicit rollback fails, the modal throws so Photoshop cancels still-suspended history. Success calls `resumeHistory(suspension,true)`.

## Verification

From `C:/Users/trong/VS Code/photoshop-mcp/uxp-plugin`:

```powershell
node --test tests/plugin.test.js
```

Ten Node mock tests cover validation, pixel dimensions/tree depth, commit, partial-write rollback, stale document checks, expiry before/inside modal and during suspension, sequential polling, result retries without replay, disconnect races, HTTP 400 stopping, and incompatible protocol rejection. They do not prove Photoshop rendering or native history behavior.

Before enabling UXP for normal use, run these manual checks on a disposable test document: valid/invalid token; nested group document query; rename/toggle/opacity update and one Undo restoring all changes; locked-layer error; closed target before a queued update; bridge interruption/restart during result delivery. Check keyboard Tab/Shift+Tab, button activation, native focus indicators, password masking, and Vietnamese status readability. Record the host version and outcomes. Keep COM default until those checks pass.

## Adobe sources consulted

- [Manifest v5 and network permissions](https://developer.adobe.com/photoshop/uxp/2022/guides/uxp-guide/uxp-misc/manifest-v5/)
- [Photoshop apiVersion 2 manifest](https://developer.adobe.com/photoshop/uxp/2022/guides/uxp-guide/uxp-misc/manifest-v4/photoshop-manifest/)
- [Network I/O: fetch, XHR and WebSockets](https://developer.adobe.com/photoshop/uxp/2022/guides/uxp-guide/uxp-misc/network-io/)
- [Document DOM: pixel dimensions and IDs](https://developer.adobe.com/photoshop/uxp/2022/ps-reference/classes/document/)
- [Layer DOM: group children and writable properties](https://developer.adobe.com/photoshop/uxp/2022/ps-reference/classes/layer/)
- [Modal execution and history commit/rollback](https://developer.adobe.com/photoshop/uxp/2022/ps-reference/media/executeasmodal/)

## Modern Web Guidance

Loaded the mandatory skill, searched `label password input`, and retrieved `forms,accessibility`. Used visible labels, persistent hints, validation after user action, native keyboard controls/focus, and text status announcements. UXP limitations override browser assumptions: block/flex CSS, native XHR timeout, native button activation instead of form navigation, and no modern pseudo-class dependencies. The explicit no-token-persistence requirement overrides password-autofill recommendations, so autocomplete is disabled.
