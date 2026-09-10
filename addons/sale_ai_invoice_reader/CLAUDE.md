# CLAUDE.md — sale_ai_invoice_reader (v1.3)

**Bóc tách hóa đơn ảnh/PDF bằng Gemini API, điền dữ liệu vào sale.order.**

## Phụ thuộc
- **Lên:** `dac_erp`, `sale`, `sale_management`, `account`, `product`
- **Xuống:** không có addon nào phụ thuộc addon này

## File chính
| File | Nội dung |
|---|---|
| `models/sale_order.py` | Extends sale.order với AI invoice reader methods + 4 transient models |
| `models/res_config_settings.py` | gemini.api.key, gemini.model.priority, res.config.settings extend |
| `views/sale_order_views.xml` | Kế thừa **anchor** `dac_erp.dac_sale_order_custom_view_form` |
| `views/res_config_settings_views.xml` | Kế thừa `sale.res_config_settings_view_form` |

## Điểm dễ vỡ — DANGER ZONES (→ [`docs/DANGER_ZONES.md`](../../docs/DANGER_ZONES.md) §3.3)

### View anchor dùng chung — QUAN TRỌNG
`views/sale_order_views.xml` kế thừa `dac_erp.dac_sale_order_custom_view_form`.
View này được định nghĩa trong `dac_erp/views/sale_order_ui_simplify_view.xml` và cũng bị
kế thừa bởi `dac_erp/views/dac_work_task_views.xml`.

**Nếu `dac_erp` đổi cấu trúc view lõi này:**
- Form AI invoice reader có thể render sai / mất section
- Phải upgrade cả `sale_ai_invoice_reader` sau khi upgrade `dac_erp`
- Test: mở sale order form → kiểm tra tab/button AI invoice còn hiển thị đúng

### Computed store=True
- `subtotal` trên `gemini.invoice.line.preview` (`models/sale_order.py:345`)
  depends: `quantity`, `price_unit`
- `total_wizard` trên wizard depends: `line_ids.subtotal`

## Đọc gì trước khi sửa
1. `docs/DANGER_ZONES.md` §3.3 (view anchor dùng chung)
2. `docs/MODULE_REGISTRY.md` (dependency map)
3. `addons/dac_erp/CLAUDE.md` (anchor view `dac_sale_order_custom_view_form`)
4. Sau khi sửa view: upgrade cả `dac_erp` + `sale_ai_invoice_reader` + kiểm tra form
