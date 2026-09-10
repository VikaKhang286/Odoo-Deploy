# dac-erp CLI Skill — Reference Guide

## Overview

`dac-erp` là CLI chính thức để OpenClaw tương tác với Odoo DAC ERP. Mọi truy cập Odoo **phải đi
qua CLI này hoặc MCP adapter** — không gọi raw `/dac_erp/api/v3` trực tiếp.

Base URL: `https://crm.duyan.vn`  
Auth header: `X-MCP-API-KEY` (read key hoặc write key tùy command)

---

## AI Tag System v2

### Quy tắc quan trọng

| Quy tắc | Chi tiết |
|---|---|
| **Dry-run là mặc định** | `conversation tags set` không truyền `--apply` → chỉ preview, không ghi DB |
| **Apply thật cần `--apply`** | Phải truyền `--apply` + `--reason` + `--evidence` |
| **Mode chuẩn** | `replace_ai_scope` — chỉ thay tag `managed_by_ai=True`, giữ nguyên tag thủ công/VIP |
| **`replace_all` bị chặn** | MCP chặn hoàn toàn, không dùng mode này qua CLI |
| **`customer_vip` không bị AI thay** | `managed_by_ai=False`, xuất hiện trong `not_ai_managed_codes` nếu truyền vào |
| **`needs_review` / `do_not_apply_reason`** | Log intent, không apply tag, `applied=false` |
| **Idempotency** | Apply thật cần `request_id` cố định (UUID) — cùng ID → replay an toàn |

### Tag chuẩn (managed_by_ai=True)

| Code | Label |
|---|---|
| `needs_action` | Cần xử lý |
| `waiting_customer_reply` | Chờ khách phản hồi |
| `recontact_needed` | Chăm lại |
| `payment_due_after_production` | Chưa thu tiền |
| `customer_purchased` | Đã mua hàng |
| `customer_repeat` | Khách quen |
| `lost_or_cold` | Fail |
| `done` | Done |

### Tag thủ công / VIP (managed_by_ai=False)

| Code | Label | Ghi chú |
|---|---|---|
| `customer_vip` | Khách lớn | AI không được replace/apply/xóa |

---

## Commands — Tag System

### B1. Liệt kê tag chuẩn

```bash
dac-erp tag list --scope ai_managed --json
dac-erp tag list --scope ai_managed --page-id 12 --json
```

- `--scope ai_managed` lọc chỉ tag `managed_by_ai=True` (default)
- `--page-id` optional, lọc theo Pancake page

**Sample output:**
```json
{
  "ok": true,
  "command": "tag list",
  "filters": { "scope": "ai_managed" },
  "count": 8,
  "total": 8,
  "items": [
    {
      "id": 1,
      "page_id": 5,
      "page_name": "DAC Fanpage",
      "tag_fm_id": "abc123",
      "name": "Cần xử lý",
      "odoo_tag_code": "needs_action",
      "managed_by_ai": true,
      "active": true
    }
  ]
}
```

### B2. Đọc tags của hội thoại

```bash
dac-erp conversation tags get --conversation-id 1234 --json
```

**Sample output:**
```json
{
  "ok": true,
  "command": "conversation tags get",
  "conversation_id": "1234",
  "tags_count": 2,
  "tags": [
    { "id": 1, "name": "Cần xử lý", "odoo_tag_code": "needs_action", "managed_by_ai": true },
    { "id": 9, "name": "Khách lớn", "odoo_tag_code": "customer_vip", "managed_by_ai": false }
  ]
}
```

### B3. Dry-run (preview — không mutate)

```bash
dac-erp conversation tags set \
  --conversation-id 1234 \
  --tag-codes needs_action,customer_purchased \
  --mode replace_ai_scope \
  --reason "AI labeling after reading conversation" \
  --evidence "Khách hỏi giá ngày 2026-06-09 chưa thấy báo giá" \
  --confidence 0.87 \
  --json
```

> ⚠ Không có `--apply` → `dry_run=true` → không ghi DB, không sync Pancake.

**Sample output:**
```json
{
  "ok": true,
  "command": "conversation tags set",
  "dry_run": true,
  "conversation_id": "1234",
  "mode": "replace_ai_scope",
  "applied": false,
  "would_add": ["needs_action", "customer_purchased"],
  "would_remove": ["waiting_customer_reply"],
  "kept_manual_tag_codes": ["customer_vip"],
  "not_ai_managed_codes": [],
  "pancake_sync": { "enabled": true, "synced": false, "results": [], "local_tags_skipped": 0 }
}
```

### B4. Apply thật (mutation — cần xác nhận rõ)

```bash
dac-erp conversation tags set \
  --conversation-id 1234 \
  --tag-codes needs_action,customer_purchased \
  --mode replace_ai_scope \
  --apply \
  --request-id "550e8400-e29b-41d4-a716-446655440000" \
  --reason "Approved: AI labeling after review" \
  --evidence "Khách hỏi giá ngày 2026-06-09 chưa thấy báo giá" \
  --confidence 0.87 \
  --json
```

> ✅ `--apply` → `dry_run=false` → ghi DB, sync Pancake, lưu audit log.
> Nếu không truyền `--request-id`, CLI tự generate UUID và in ra `generated_request_id`.

**Sample output:**
```json
{
  "ok": true,
  "command": "conversation tags set",
  "dry_run": false,
  "conversation_id": "1234",
  "mode": "replace_ai_scope",
  "applied": true,
  "applied_tag_codes": ["needs_action", "customer_purchased"],
  "added_tag_codes": ["needs_action", "customer_purchased"],
  "removed_tag_codes": ["waiting_customer_reply"],
  "kept_manual_tag_codes": ["customer_vip"],
  "not_ai_managed_codes": [],
  "pancake_sync": { "enabled": true, "synced": true, "results": [...], "local_tags_skipped": 0 },
  "log_id": 42,
  "idempotent_replay": false
}
```

### B5. needs_review / log intent (không mutate)

```bash
dac-erp conversation tags set \
  --conversation-id 1234 \
  --tag-codes needs_action \
  --mode replace_ai_scope \
  --needs-review \
  --do-not-apply-reason "missing evidence" \
  --reason "AI uncertain after reading conversation" \
  --evidence "Conversation lacks clear customer intent" \
  --confidence 0.1 \
  --json
```

> `--needs-review` hoặc `--do-not-apply-reason` → log intent, `applied=false`.

---

## Flags Reference — `conversation tags set`

| Flag | Required | Default | Description |
|---|---|---|---|
| `--conversation-id` | ✅ | — | Odoo conversation ID |
| `--tag-codes` | ✅ | — | Comma-separated tag codes |
| `--mode` | — | `replace_ai_scope` | Tag replace mode |
| `--apply` | — | false | Set `dry_run=false`; without this flag, preview only |
| `--request-id` | cần khi `--apply` | auto-UUID | Idempotency key |
| `--reason` | cần khi `--apply` | — | Why AI is applying |
| `--evidence` | cần khi `--apply` | — | Pipe-delimited evidence strings |
| `--confidence` | — | — | Float 0–1 |
| `--needs-review` | — | false | Flag for human review; no mutation |
| `--do-not-apply-reason` | — | — | Text reason to skip; no mutation |
| `--agent-name` | — | `OpenClaw` | AI agent identifier |
| `--model-name` | — | — | Model name for audit |

---

## Policy: OpenClaw không gọi raw API

```
❌ KHÔNG làm:  curl -X PUT https://crm.duyan.vn/dac_erp/api/v3/conversations/1234/tags -H "X-API-KEY: ..."
✅ ĐÚNG:       dac-erp conversation tags set --conversation-id 1234 --tag-codes needs_action --json
```

MCP adapter (`/dac_erp/mcp/v1/`) xác thực bằng `X-MCP-API-KEY`, có thêm lớp safety:
- Default dry-run
- replace_all bị chặn  
- Validation đầy đủ trước khi gọi business logic

---

## Xem thêm

- [mcp-api-v1.md](references/mcp-api-v1.md) — API reference đầy đủ cho tag routes
- [CLAUDE.md](../../../CLAUDE.md) — Project rules
