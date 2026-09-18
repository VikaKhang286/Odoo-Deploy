# CLAUDE.md — dac_openclaw (v1.0)

**Lớp webhook OUTBOUND.** Fire event tới OpenClaw AI khi order/conversation/task thay đổi.
Chỉ có hook models — không có views riêng, không có ACL riêng.

## Phụ thuộc
- **Lên:** `dac_erp`, `CRM_DAC`
- **Xuống:** không có addon nào phụ thuộc dac_openclaw

## File chính
| File | Model hook | Event được fire |
|---|---|---|
| `models/sale_order_hooks.py` | sale.order | `order.created`, `order.stage_changed`, `order.cancelled`, `order.reopened` |
| `models/dac_work_task_hooks.py` | dac.work.task | `task.created`, `task.assigned`, `task.completed` |
| `models/page_fm_conversation_hooks.py` | page.fm.conversation | `conversation.assigned`, `conversation.status_changed` |
| `models/outbound_webhook_log.py` | dac_openclaw.outbound.webhook.log | Log event |
| `services/` (trong dac_erp) | — | `openclaw_notification_service.py` gửi HTTP |

## Điểm dễ vỡ — DANGER ZONES (→ [`docs/DANGER_ZONES.md`](../../docs/DANGER_ZONES.md) §3.1)

### Phụ thuộc ngầm vào method signature của addon khác
3 hook model gọi `super().create/write()` trực tiếp lên model ở addon khác:
- `sale_order_hooks.py:42` → `sale.order.create()` trong **dac_erp** (`sale_order.py:768`)
- `dac_work_task_hooks.py:39` → `dac.work.task.create()` trong **dac_erp** (`dac_work_task.py:161`)
- `page_fm_conversation_hooks.py:35` → `page.fm.conversation.write()` trong **CRM_DAC**

**Hậu quả:** Bất kỳ thay đổi nào ở dac_erp/CRM_DAC làm:
- đổi chữ ký method (thêm/xóa param)
- thêm context guard mới
- raise exception mới

→ hook của dac_openclaw bị vỡ hoặc miss event mà **không có lỗi rõ ràng**.

### Không có @api.constrains / @api.onchange / @api.ondelete
Các hook model chỉ có create/write — không validate dữ liệu event trước khi fire.
Dữ liệu sai → event fire với payload sai, OpenClaw xử lý nhầm.

## Đọc gì trước khi sửa
1. `docs/DANGER_ZONES.md` §3.1 (override super liên-addon)
2. `docs/MODULE_REGISTRY.md` (phụ thuộc của cả dac_erp và CRM_DAC)
3. `docs/OPENCLAW_MCP_API_REFERENCE.md` (khi sửa event payload / route)
4. `docs/openclaw_integration_workflow.md` (luồng tổng thể)
5. `docs/OPENCLAW_MCP_AGENT_POLICY.md` (khi thay đổi logic fire event)
6. Sau khi sửa: chạy test `/dac_erp` + `/CRM_DAC` để kiểm tra super chain còn intact
