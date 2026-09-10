# CLAUDE.md — CRM_DAC (v4.1)

**Đồng bộ hội thoại Pancake/Pages.fm + KPI nhân viên.** Quản lý conversation, message, tag,
sync job queue, và KPI bán hàng theo ngày.

## Phụ thuộc
- **Lên:** `dac_erp`, `home_menu`
- **Xuống (bị phụ thuộc bởi):** `dac_report`, `dac_openclaw`

> `page.fm.conversation.write()` là **đích hook** của `dac_openclaw`. Sửa method này → kiểm tra dac_openclaw.

## File chính
| File | Nội dung |
|---|---|
| `models/page_fm_conversation_models.py` | page.fm.conversation ~2885+ dòng — model chính |
| `models/page_fm_message_models.py` | page.fm.message |
| `models/page_fm_models.py` | page.fm.page |
| `models/page_fm_tag.py` | page.fm.tag |
| `models/pancake_message_sync_job.py` | pancake.message.sync.job (~762+ dòng) + pancake.message.sync.log |
| `models/res_ext.py` | Extends res.users (pancake_id/uuid) và res.partner (pancake_id, conversation_ids) |
| `models/kpi_sale_daily.py` | kpi.sale.daily |
| `controllers/main.py` | `/pancake/dashboard` (auth='public'!) + `/pancake/trigger_sync_all` |

## Điểm dễ vỡ — DANGER ZONES (→ [`docs/DANGER_ZONES.md`](../../docs/DANGER_ZONES.md))

### Computed store=True — §3.2
| Field | @api.depends |
|---|---|
| `name` trên page.fm.conversation (page_fm_conversation_models.py:58) | customer_name_fm, conversation_fm_id |
| `message_count` (page_fm_conversation_models.py:100) | conv_message_ids |
| `last_message_at_fm` (page_fm_conversation_models.py:128) | conv_message_ids.inserted_at_fm |
| `conversation_count` trên page.fm.page (page_fm_models.py:65) | conversation_ids |
Đổi field nguồn trong `depends` → recompute hàng loạt + có thể mất index search.

### ACL thiếu — §3.5
`page.fm.conversation` và `page.fm.message` **không có dòng ACL riêng** trong ir.model.access.csv.
Truy cập chỉ được kiểm soát bởi record rule (nếu có). Xem OPEN_QUESTIONS §8.

### Route công khai — OPEN_QUESTIONS §3
`/pancake/dashboard` (controllers/main.py:11) `auth='public'` — không có secret/API key.
Bất kỳ ai cũng có thể đọc dữ liệu tổng hợp Pancake.

### Hook từ dac_openclaw
`page.fm.conversation.write()` được `dac_openclaw/models/page_fm_conversation_hooks.py:35`
gọi super. Sửa write() ở đây → kiểm tra event `conversation.assigned` / `conversation.status_changed`
còn fire đúng không.

## Đọc gì trước khi sửa
1. `docs/DANGER_ZONES.md` §3.1, §3.2, §3.5
2. `docs/MODULE_REGISTRY.md` cột "Bị phụ thuộc bởi"
3. `docs/PANCAKE_TOKEN_FLOW.md` (khi sửa auth/sync)
4. `docs/message_sync_simplification/04_pancake_api_usage_contract.md` (khi sửa Pancake API calls)
5. `docs/OPENCLAW_MCP_MESSAGE_API_SPEC.md` (khi sửa message endpoint)
6. `docs/MESSENGER_API_REFERENCE.md` (khi sửa Send API, Webhook events, Message Tags, 24h window)
7. Chạy test `/CRM_DAC` sau khi sửa; nếu sửa write() → cũng chạy `/dac_openclaw`
