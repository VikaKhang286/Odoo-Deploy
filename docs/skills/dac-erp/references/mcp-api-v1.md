# MCP API v1 — Tag Routes Reference

Base URL: `https://crm.duyan.vn`  
Auth header: `X-MCP-API-KEY: <key>`

---

## GET /dac_erp/mcp/v1/tags

List standard Pancake tags, optionally filtered by page and AI-management scope.

**Auth:** readKey OR writeKey  
**Mutation:** None

### Query Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `page_id` | int | — | Filter by `page.fm.page.id` |
| `scope` | string | — | `ai_managed` → only `managed_by_ai=True` tags |

### Response — 200

```json
{
  "ok": true,
  "count": 8,
  "total": 8,
  "_envelope_type": "list",
  "items": [
    {
      "id": 1,
      "page_id": 5,
      "page_name": "DAC Fanpage",
      "tag_fm_id": "abc123",
      "name": "Cần xử lý",
      "odoo_tag_code": "needs_action",
      "odoo_tag_label": "Cần xử lý",
      "managed_by_ai": true,
      "fm_color_hex": "#ff0000",
      "active": true
    }
  ]
}
```

### Error Responses

| Status | code | When |
|---|---|---|
| 401 | `missing_api_key` | No `X-MCP-API-KEY` header |
| 403 | `invalid_api_key` | Key not recognized |
| 400 | `invalid_page_id` | `page_id` not an integer |

---

## GET /dac_erp/mcp/v1/conversations/{conversation_id}/tags

Read current Pancake tags on a specific conversation.

**Auth:** readKey OR writeKey  
**Mutation:** None

### Path Parameters

| Param | Type | Description |
|---|---|---|
| `conversation_id` | int | Odoo `page.fm.conversation` ID |

### Response — 200

```json
{
  "ok": true,
  "_envelope_type": "detail",
  "data": {
    "conversation_id": 1234,
    "tags_count": 2,
    "tags": [
      {
        "id": 1,
        "tag_fm_id": "abc123",
        "name": "Cần xử lý",
        "odoo_tag_code": "needs_action",
        "managed_by_ai": true,
        "active": true
      },
      {
        "id": 9,
        "tag_fm_id": "xyz999",
        "name": "Khách lớn",
        "odoo_tag_code": "customer_vip",
        "managed_by_ai": false,
        "active": true
      }
    ]
  }
}
```

### Error Responses

| Status | code | When |
|---|---|---|
| 401 | `missing_api_key` | No `X-MCP-API-KEY` |
| 403 | `invalid_api_key` | Key not recognized |
| 404 | `not_found` | Conversation ID not found |

---

## PUT /dac_erp/mcp/v1/conversations/{conversation_id}/tags

Set AI-managed tags on a conversation.

**Auth:** writeKey only (readKey → 403 `insufficient_permission`)  
**Mutation:** YES — writes to DB and syncs Pancake (unless `dry_run=true`)

### Safety Guarantees

- **`dry_run` defaults to `true`** if not explicitly passed. Pass `"dry_run": false` only when ready to apply.
- **`replace_all` mode is BLOCKED.** Use `replace_ai_scope`.
- **`managed_by_ai=False` tags are never mutated** (`customer_vip` etc. appear in `not_ai_managed_codes`).
- **When `dry_run=false`: `request_id`, `reason`, and `evidence` (≥1 item) are required.**
- Duplicate `request_id` with same payload → idempotent replay (safe to retry).
- Duplicate `request_id` with different payload → 409 conflict.

### Request Body

```json
{
  "tag_codes": ["needs_action", "customer_purchased"],
  "mode": "replace_ai_scope",
  "dry_run": true,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent_name": "OpenClaw",
  "reason": "AI labeling after reading conversation",
  "evidence": ["Khách hỏi giá ngày 2026-06-09 chưa thấy báo giá"],
  "confidence": 0.87,
  "needs_review": false,
  "do_not_apply_reason": null,
  "model_name": "claude-sonnet-4-6"
}
```

### Request Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `tag_codes` | `string[]` | ✅ | — | Tag codes to apply. Unknown codes → `validation_error`. |
| `mode` | string | — | `replace_ai_scope` | `replace_ai_scope` \| `add` \| `remove`. `replace_all` is BLOCKED. |
| `dry_run` | boolean | — | **`true`** | `false` = real write. |
| `request_id` | string | when `dry_run=false` | auto-UUID | Idempotency key. |
| `agent_name` | string | — | `OpenClaw` | AI agent name for audit. |
| `reason` | string | when `dry_run=false` | — | Human-readable reason. |
| `evidence` | `string[]` | when `dry_run=false` | `[]` | Supporting evidence from conversation. |
| `confidence` | float | — | — | 0–1. |
| `needs_review` | boolean | — | `false` | If `true`: log intent only, `applied=false`. |
| `do_not_apply_reason` | string | — | — | Text reason to skip; triggers `applied=false`. |
| `model_name` | string | — | — | AI model name for audit. |

### Response — 200

**Dry-run response:**
```json
{
  "ok": true,
  "_envelope_type": "detail",
  "data": {
    "conversation_id": 1234,
    "mode": "replace_ai_scope",
    "dry_run": true,
    "applied": false,
    "requested_tag_codes": ["needs_action", "customer_purchased"],
    "applied_tag_codes": [],
    "would_add": ["needs_action", "customer_purchased"],
    "would_remove": ["waiting_customer_reply"],
    "added_tag_codes": [],
    "removed_tag_codes": [],
    "kept_manual_tag_codes": ["customer_vip"],
    "not_ai_managed_codes": [],
    "pancake_sync": {
      "enabled": true,
      "synced": false,
      "results": [],
      "local_tags_skipped": 0
    },
    "generated_request_id": "auto-uuid-if-not-provided"
  }
}
```

**Apply response (`dry_run=false`):**
```json
{
  "ok": true,
  "_envelope_type": "detail",
  "data": {
    "conversation_id": 1234,
    "mode": "replace_ai_scope",
    "dry_run": false,
    "applied": true,
    "requested_tag_codes": ["needs_action", "customer_purchased"],
    "applied_tag_codes": ["needs_action", "customer_purchased"],
    "would_add": [],
    "would_remove": [],
    "added_tag_codes": ["needs_action", "customer_purchased"],
    "removed_tag_codes": ["waiting_customer_reply"],
    "kept_manual_tag_codes": ["customer_vip"],
    "not_ai_managed_codes": [],
    "pancake_sync": {
      "enabled": true,
      "synced": true,
      "results": [
        { "tag_code": "needs_action", "action": "add", "success": true }
      ],
      "local_tags_skipped": 0
    },
    "log_id": 42,
    "idempotent_replay": false
  }
}
```

**needs_review / do_not_apply_reason response:**
```json
{
  "ok": true,
  "_envelope_type": "detail",
  "data": {
    "conversation_id": 1234,
    "mode": "replace_ai_scope",
    "dry_run": false,
    "applied": false,
    "not_applied_reason": "needs_review",
    "log_id": 43,
    "idempotent_replay": false
  }
}
```

### Error Responses

| Status | code | When |
|---|---|---|
| 401 | `missing_api_key` | No `X-MCP-API-KEY` |
| 403 | `insufficient_permission` | readKey used on write route |
| 403 | `invalid_api_key` | Key not recognized |
| 400 | `invalid_request` | Missing/invalid field |
| 400 | `missing_request_id` | `dry_run=false` + no `request_id` |
| 400 | `missing_reason` | `dry_run=false` + no `reason` |
| 400 | `missing_evidence` | `dry_run=false` + empty `evidence` |
| 400 | `unsafe_mode` | `replace_all` attempted |
| 404 | `not_found` | Conversation not found |
| 409 | `conflict` | Same `request_id`, different payload |
| 500 | `internal_error` | Server error |

---

## Tag Mode Behavior

| Mode | AI tags (`managed_by_ai=True`) | Manual tags (`managed_by_ai=False`) |
|---|---|---|
| `replace_ai_scope` | Replaced with `tag_codes` | Preserved unchanged |
| `add` | Added (no removal) | Preserved unchanged |
| `remove` | Removed if in `tag_codes` | Preserved unchanged |
| `replace_all` | **BLOCKED via MCP** | **BLOCKED via MCP** |

---

## `local_tags_skipped` — Local vs Pancake tags

Tags synced to DB (`page.fm.tag`) but not yet pushed to Pancake (no `tag_fm_id`) are counted in
`pancake_sync.local_tags_skipped`. They exist in Odoo but cannot be synced to Pancake without a
real `tag_fm_id`. Use `tag list --scope ai_managed` to check which tags have `tag_fm_id`.
