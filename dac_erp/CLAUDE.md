# CLAUDE.md — dac_erp (v8.0)

**Lõi ERP.** Đơn hàng, workflow sale→design→production→delivery, hóa đơn/thanh toán, MCP AI
agent, Pancake webhook, API v2/v3. **101 file .py, 36 file .xml.**

## Phụ thuộc
- **Lên:** `home_menu`, `Chameleon`, `sale`, `sale_management`, `account`, `product`
- **Xuống (bị phụ thuộc bởi):** `CRM_DAC`, `dac_report`, `dac_openclaw`, `sale_ai_invoice_reader`

> Sửa bất kỳ method/field nào trong addon này → kiểm tra 4 addon hạ nguồn trước khi merge.

## File chính
| File | Nội dung |
|---|---|
| `models/sale_order.py` | sale.order ~1213 dòng; state machine, 60+ fields, tất cả actions |
| `models/account_move.py` | account.move ~612 dòng; deposit/payment flow |
| `models/account_payment.py` | account.payment; access control, reconcile |
| `models/account_payment_register.py` | **⚠ inherit='account.payment'** (không phải account.payment.register!) |
| `models/dac_work_task.py` | task model + sync 2 chiều với sale.order |
| `models/dashboard.py` | KPI methods trên sale.order |
| `models/sale_order_sever_copy.py` | pancake_* fields trên sale.order |
| `controllers/pancake_webhook_controller.py` | `/dac_erp/pancake_webhook` auth='none' |
| `controllers/` (mcp_*, v2, v3) | Toàn bộ API suite |
| `services/` | pancake_messaging, openclaw_notification, mcp_normalizer, mcp_rate_limit |
| `security/ir.model.access.csv` | ACL — `mcp_*_log` chỉ R cho Manager |
| `security/sale_order_access_rules.xml` | Record rules theo user_id/user_id_design/production_group_ids |
| `security/account_access_rules.xml` | Record rules theo dac_user_id |
| `security/dac_work_task_access_rules.xml` | Record rules task |
| `views/sale_order_ui_simplify_view.xml` | Định nghĩa **anchor** `dac_sale_order_custom_view_form` |

## Điểm dễ vỡ — DANGER ZONES (→ [`docs/DANGER_ZONES.md`](../../docs/DANGER_ZONES.md))

### Override super() critical
- `sale_order.py:write()` ↔ `dac_work_task.py:write()` sync 2 chiều dùng context `dac_skip_task_sync` / `dac_skip_order_sync`. Bỏ context này → **vòng lặp vô tận**.
- `account_move.py:write()` trigger khi `payment_state='paid'` → deposit/completion flow. Sai → đơn không tự hoàn tất.
- `sale_order.py:create()` kết quả được `dac_openclaw/models/sale_order_hooks.py:42` gọi super. Đổi chữ ký → vỡ OpenClaw event.

### View anchor dùng chung
- `dac_sale_order_custom_view_form` bị kế thừa bởi: `dac_work_task_views.xml` + `sale_ai_invoice_reader`. Sửa view này → kiểm tra tab Task và form AI invoice.
- `account.view_move_form` bị 2 file trong addon này kế thừa: `account_move_view.xml` + `account_move_deposit_view.xml`.

### Record rule ngầm
- `dac_user_id` trên account.move/payment **phải được set khi tạo** (account_move.py:170 set trong create). Nếu thiếu → Sale user thấy rỗng mà không có lỗi.
- `user_id_design`, `user_id_production`, `production_group_ids` tương tự trên sale.order.

### Bẫy đặt tên
- `account_payment_register.py` inherit `account.payment` (không phải `account.payment.register`). Cả 2 file cùng override `read()/web_read()` — thứ tự áp dụng phụ thuộc load order.

## Đọc gì trước khi sửa
1. `docs/DANGER_ZONES.md` §3.1–3.5
2. `docs/MODULE_REGISTRY.md` cột "Bị phụ thuộc bởi"
3. `docs/DAC_ERP_CURRENT_API_REFERENCE.md` (khi sửa controller/route)
4. `docs/MCP_V2_API.md` (khi sửa MCP API)
5. Chạy agent `regression-checker` sau khi sửa
