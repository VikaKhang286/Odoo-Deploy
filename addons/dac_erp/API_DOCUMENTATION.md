# DAC ERP - Data Export API Documentation

> Ghi chú: file này là tài liệu legacy, vẫn hữu ích để tham chiếu lịch sử nhưng không còn là bản đầy đủ nhất.
> Bản reference hiện hành, đã bao gồm `v2`, `v3`, webhook, route legacy, debug, và internal routes, nằm tại:
> [docs/DAC_ERP_CURRENT_API_REFERENCE.md](/home/administrator/odoo-antigravity/docs/DAC_ERP_CURRENT_API_REFERENCE.md)

## Tổng quan

API này cung cấp khả năng export và quản lý toàn bộ dữ liệu từ hệ thống Odoo bao gồm:

- **Đơn hàng** (Sales Orders) với conversation tracking
- **Khách hàng** (Customers) với lọc theo trạng thái đơn hàng
- **Hóa đơn** (Invoices)
- **Phiếu thu** (Payments)
- **Nhân viên** (Employees)
- **Sản phẩm** (Products)
- **Tin nhắn** (Messages) từ Pages.fm/Pancake
- **Hội thoại** (Conversations) từ Pages.fm/Pancake

## Authentication

- API sử dụng `auth='public'` với `csrf=False`
- Không yêu cầu đăng nhập cho các endpoint export
- Sử dụng `.sudo()` để truy cập dữ liệu

## Base URL

```
http(s)://<your-domain>/dac_erp/api/export/
```

**Ví dụ:**

- Development: `http://localhost:8069/dac_erp/api/export/`
- Production: `https://crm.duyan.vn/dac_erp/api/export/`

## Endpoints

---

### 1. Export All Data

**GET/POST** `/dac_erp/api/export/all`

Export tất cả dữ liệu cùng lúc (đơn hàng, khách hàng, hóa đơn, phiếu thu, nhân viên, sản phẩm, thống kê).

**Parameters:**
Nhận tất cả parameters từ các endpoint con (sales, customers, invoices, payments, employees, products).

**Response:**

```json
{
  "sales": {
    "count": 100,
    "items": [...]
  },
  "customers": {
    "count": 150,
    "items": [...]
  },
  "invoices": [...],
  "payments": [...],
  "employees": [...],
  "products": [...],
  "summary": {
    "total_orders": 1000,
    "total_customers": 500,
    "total_revenue_this_month": 50000000,
    "orders_by_state": {...}
  }
}
```

---

### 2. Export Sales Data

**GET/POST** `/dac_erp/api/export/sales`

Export dữ liệu đơn hàng với nhiều bộ lọc và hỗ trợ conversation từ Pages.fm/Pancake.

#### Parameters - Thời gian:

- `date` (string): Lấy đơn hàng của 1 ngày cụ thể (format: YYYY-MM-DD)
- `date_from` (string): Từ ngày (format: YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS)
- `date_to` (string): Đến ngày (format: YYYY-MM-DD hoặc YYYY-MM-DD HH:MM:SS)
- `date_field` (string): Field để lọc ngày - `date` | `date_order` | `create_date` (default: `date`)

#### Parameters - Bộ lọc cơ bản:

- `limit` (int): Số lượng đơn hàng (default: 100)
- `offset` (int): Vị trí bắt đầu (default: 0)
- `order` (string): Sắp xếp (default: `date desc`)
- `user_id` (int|'me'): ID người phụ trách hoặc `me` cho user hiện tại
- `partner_id` (int): ID khách hàng
- `company_id` (int): ID công ty
- `conversation_id` (int): ID conversation trong Odoo
- `pancake_conversation_id` (string): ID conversation từ Pancake

#### Parameters - Trạng thái:

- `state` (CSV string): Trạng thái đơn hàng (ví dụ: `draft,sent,sale,done,cancel`)
- `custom_state` (CSV string): Trạng thái custom (ví dụ: `quotation,deposit,production,delivery,payment`)
- `has_deposit` (0|1): Lọc đơn có/không có cọc
- `is_order_completed` (0|1): Lọc đơn đã/chưa hoàn thành

#### Parameters - Số liệu:

- `min_total` (float): Tổng tiền tối thiểu
- `max_total` (float): Tổng tiền tối đa

#### Parameters - Hiển thị:

- `include_lines` (0|1): Hiển thị chi tiết dòng hàng (default: 1)
- `include_conversation` (0|1): Hiển thị thông tin conversation (default: 1)
- `conv_limit` (int|'all'): Số lượng conversation muốn lấy (default: 3, `all` = 100)
- `format` ('flat'): Trả về list thuần không có metadata (backward compatibility)

#### Response Structure:

```json
{
  "count": 100,
  "limit": 100,
  "offset": 0,
  "order": "date desc",
  "date_field": "date",
  "domain": [...],
  "items": [
    {
      "id": 1,
      "name": "S00001",
      "order_number": "ORD-001",
      "client_order_ref": "REF-001",
      "date": "2025-01-01T00:00:00",
      "date_order": "2025-01-01T00:00:00",
      "create_date": "2025-01-01T00:00:00",
      "state": "production",
      "order_state_custom": "production",

      "amounts": {
        "untaxed": 909090.91,
        "tax": 90909.09,
        "total": 1000000
      },

      "flags": {
        "has_deposit": true,
        "is_completed": false,
        "is_priority": false,
        "is_priority_today": false
      },

      "customer": {
        "id": 10,
        "name": "Nguyễn Văn A",
        "phone": "0123456789",
        "address": "123 ABC Street"
      },

      "people": {
        "sale": {"id": 2, "name": "Sale User"},
        "designer": {"id": 3, "name": "Designer User"},
        "producer": {"id": 4, "name": "Producer User"},
        "production_group": [{"id": 1, "name": "Nhóm SX 1"}]
      },

      "deposit": {
        "enabled": true,
        "amount": 500000
      },

      "design": {
        "link": "https://design-link.com"
      },

      "production": {
        "deadline": "2025-01-15T00:00:00",
        "is_delayed": false,
        "delay_date": null,
        "delay_reason": null
      },

      "delivery": {
        "address": "123 ABC Street"
      },

      "installation": {
        "address": "456 XYZ Construction Site"
      },

      "conversation_id": 123,
      "pancake_conversation_id": "conv_abc123",
      "conversation": {
        "id": 123,
        "name": "Nguyễn Văn A",
        "pancake_id": "conv_abc123",
        "status": "new",
        "require_processing": true,
        "updated_at": "2025-01-01T10:00:00",
        "last_message": "Tin nhắn cuối...",
        "external_url": "https://pages.fm/...",
        "tags": [
          {"id": 1, "name": "VIP", "fm_id": "tag_123", "color": "#ff0000"}
        ]
      },

      "conversations": {
        "count": 3,
        "primary_id": 123,
        "items": [...]
      },

      "lines": [
        {
          "id": 1,
          "product": {"id": 5, "name": "Product ABC"},
          "name": "Product ABC",
          "qty": 1,
          "price_unit": 1000000,
          "subtotal": 1000000,
          "display_type": false
        }
      ]
    }
  ]
}
```

**Ví dụ:**

```bash
# Lấy đơn hàng của 1 ngày
GET /dac_erp/api/export/sales?date=2025-01-15

# Lấy đơn hàng của người phụ trách, trạng thái production
GET /dac_erp/api/export/sales?user_id=me&state=production&limit=50

# Lấy đơn hàng theo conversation Pancake
GET /dac_erp/api/export/sales?pancake_conversation_id=conv_abc123

# Lấy đơn có tổng tiền từ 1-10 triệu
GET /dac_erp/api/export/sales?min_total=1000000&max_total=10000000
```

---

### 3. Export Customers Data

**GET/POST** `/dac_erp/api/export/customers`

Export dữ liệu khách hàng với filter theo trạng thái đơn hàng và conversation.

#### Parameters:

- `limit` (int): Số lượng khách hàng (default: 150)
- `include_conversation` (0|1): Hiển thị thông tin conversation (default: 1)
- `include_orders` (0|1): Hiển thị danh sách đơn hàng (default: 1)
- `include_order_details` (0|1): Hiển thị chi tiết dòng hàng trong đơn (default: 0)

#### Parameters - Filters:

- `has_orders_only` (0|1): Chỉ lấy khách hàng có đơn hàng
- `has_conversation_only` (0|1): Chỉ lấy khách hàng có conversation
- `state` (CSV string): Lọc theo trạng thái đơn hàng
- `order_state_custom` (CSV string): Lọc theo trạng thái custom

#### Response:

```json
{
  "count": 150,
  "limit": 150,
  "applied_filters": {
    "state": "production,delivery",
    "has_orders_only": "1"
  },
  "items": [
    {
      "id": 10,
      "name": "Nguyễn Văn A",
      "phone": "0123456789",
      "email": "customer@example.com",
      "mobile": "0987654321",
      "street": "123 Main St",
      "city": "Hồ Chí Minh",
      "create_date": "2025-01-01T00:00:00",
      "customer_rank": 1,

      "responsible_user": {
        "id": 2,
        "name": "Sale User",
        "login": "sale@company.com"
      },

      "conversation": {
        "id": 123,
        "pancake_conversation_id": "conv_abc123",
        "status": "new",
        "is_unread": true,
        "last_message_snippet": "Tin nhắn cuối..."
      },

      "orders": [
        {
          "id": 1,
          "name": "S00001",
          "state": "production",
          "amount_total": 1000000,
          "create_date": "2025-01-01T00:00:00"
        }
      ],

      "total_orders": 5,
      "total_invoiced": 5000000,
      "orders_by_state": {
        "production": 2,
        "delivery": 1,
        "done": 2
      },

      "has_conversation": true,
      "total_conversations": 1
    }
  ]
}
```

---

### 4. Export Invoices Data

**GET/POST** `/dac_erp/api/export/invoices`

Export dữ liệu hóa đơn.

#### Parameters:

- `limit` (int): Số lượng hóa đơn (default: 1000)
- `date_from` (string): Từ ngày
- `date_to` (string): Đến ngày

#### Response:

```json
[
  {
    "id": 1,
    "name": "INV/2025/00001",
    "partner_id": { "id": 10, "name": "Nguyễn Văn A" },
    "invoice_date": "2025-01-01",
    "invoice_date_due": "2025-01-31",
    "create_date": "2025-01-01T10:00:00",
    "amount_total": 1100000,
    "amount_untaxed": 1000000,
    "amount_tax": 100000,
    "amount_residual": 0,
    "state": "posted",
    "payment_state": "paid",
    "invoice_origin": "S00001",
    "dac_deposit_invoice": false,
    "invoice_lines": [
      {
        "id": 1,
        "product_id": { "id": 5, "name": "Product ABC" },
        "name": "Product ABC",
        "quantity": 1,
        "price_unit": 1000000,
        "price_subtotal": 1000000
      }
    ]
  }
]
```

---

### 5. Export Payments Data

**GET/POST** `/dac_erp/api/export/payments`

Export dữ liệu phiếu thu.

#### Parameters:

- `limit` (int): Số lượng phiếu thu (default: 1000)
- `date_from` (string): Từ ngày
- `date_to` (string): Đến ngày

#### Response:

```json
[
  {
    "id": 1,
    "name": "PAY/2025/00001",
    "partner_id": { "id": 10, "name": "Nguyễn Văn A" },
    "amount": 500000,
    "currency_id": { "id": 1, "name": "VND" },
    "payment_date": "2025-01-01",
    "create_date": "2025-01-01T10:00:00",
    "state": "posted",
    "payment_method_line_id": { "id": 1, "name": "Cash" },
    "memo": "Thanh toán cọc đơn S00001",
    "sale_order_origin": "S00001",
    "is_deposit_payment": true,
    "is_final_payment": false
  }
]
```

---

### 6. Export Employees Data

**GET/POST** `/dac_erp/api/export/employees`

Export dữ liệu nhân viên (từ res.users).

#### Parameters:

- `limit` (int): Số lượng nhân viên (default: 500)

---

## API v2 For AI Agents

Base URL mới:

```text
http(s)://<your-domain>/dac_erp/api/v2/
```

Các route cũ `/dac_erp/api/export/*` vẫn giữ nguyên để tương thích ngược. `v2` là route canonical cho AI Agent, tập trung vào business filters rõ nghĩa và response có metadata chuẩn:

- `applied_filters`
- `order`
- `count`
- `limit`
- `offset`

### 1. Conversations

**GET** `/dac_erp/api/v2/conversations`

Business filters:

| filter | level | date anchor | notes |
|---|---|---|---|
| `unreplied=1|0` | conversation | `last_customer_message_at` | Logic nghiệp vụ: tin khách chưa được staff phản hồi |
| `unreplied_date=today\|YYYY-MM-DD` | conversation | `last_customer_message_at` | Sugar cho 1 ngày; không dùng cùng `unreplied_date_from/to` |
| `unreplied_date_from`, `unreplied_date_to` | conversation | `last_customer_message_at` | Khoảng ngày cho customer message cuối |
| `staff_user_id` | message -> conversation | message timestamp | Staff đã trực tiếp nhắn trong conversation |
| `assignee_user_id` | conversation | n/a | `owner_id` hoặc nằm trong `participant_user_ids` |

Response bổ sung:

- `last_customer_message_at`
- `last_staff_reply_at`
- `is_unreplied`
- `unreplied_since`
- `assignee_user_ids`

Notes:

- `unread` là cờ kỹ thuật ở `page.fm.conversation.is_unread_fm`.
- `unreplied` là logic nghiệp vụ, khác với `unread`.
- Khi dùng `unreplied=1`, sort mặc định là `last_customer_message_at desc, id desc`.

Invalid combinations:

- `unreplied_date` không được đi cùng `unreplied_date_from` hoặc `unreplied_date_to`.

400 example:

```json
{
  "success": false,
  "error": "unreplied_date cannot be combined with unreplied_date_from or unreplied_date_to",
  "status_code": 400
}
```

### 2. Messages

**GET** `/dac_erp/api/v2/messages`

Business filters:

| filter | level | date anchor | notes |
|---|---|---|---|
| `conversation_unreplied=1|0` | conversation -> message | `last_customer_message_at` | Chỉ lấy messages thuộc conversations đang unreplied |
| `date`, `date_from`, `date_to` | message | `inserted_at_fm` | Hỗ trợ cross-conversation query |
| `staff_user_id` | message | `inserted_at_fm` | Chỉ lấy messages do staff đó gửi |
| `assignee_user_id` | conversation -> message | n/a | Lọc theo owner/participant của conversation |
| `conversation_id`, `conversation_fm_id` | message | n/a | Drill-down theo conversation khi cần |

Response bổ sung:

- `sender_role=customer|staff|system|unknown`

Invalid combinations:

- Không hỗ trợ `unread`, `has_unread`, `unread_only` ở level message.

400 example:

```json
{
  "success": false,
  "error": "Message-level unread filters are not supported. Allowed filters: date,date_from,date_to,conversation_unreplied,staff_user_id,assignee_user_id,conversation_id,conversation_fm_id",
  "status_code": 400
}
```

### 3. Orders

**GET** `/dac_erp/api/v2/orders`

Business filters:

| filter | level | date anchor | notes |
|---|---|---|---|
| `deposit_event=invoice_created|payment_received` | order | deposit business event | Không suy diễn từ `has_deposit + date_order` |
| `deposit_date=today\|YYYY-MM-DD` | invoice/payment -> order | `invoice_date` hoặc `payment.date` | Sugar cho 1 ngày |
| `deposit_date_from`, `deposit_date_to` | invoice/payment -> order | `invoice_date` hoặc `payment.date` | Khoảng ngày cho event |
| `has_deposit_invoice=1|0` | order | n/a | Có hay không có hóa đơn cọc hợp lệ |

Response bổ sung:

- `deposit_invoice_count`
- `latest_deposit_invoice_id`
- `latest_deposit_invoice_date`
- `deposit_payment_count`
- `latest_deposit_payment_id`
- `latest_deposit_payment_date`

Notes:

- `invoice_created` dùng `account.move.dac_deposit_invoice=True`, ưu tiên `invoice_date`, fallback `create_date`.
- `payment_received` dùng `account.payment.state='posted'` và reconcile với deposit invoice làm source of truth.

Invalid combinations:

- `deposit_date` không được đi cùng `deposit_date_from` hoặc `deposit_date_to`.

400 example:

```json
{
  "success": false,
  "error": "deposit_date cannot be combined with deposit_date_from or deposit_date_to",
  "status_code": 400
}
```

### 4. Order Write APIs

Canonical auth cho write API:

- Header: `X-API-KEY`
- System parameter: `dac_erp.api_v2_write_key`
- Content-Type: `application/json`

#### 4.1 Create Order

**POST** `/dac_erp/api/v2/orders`

Request fields:

- `partner_id` bắt buộc
- `conversation_id` tùy chọn, chỉ set lúc tạo
- `user_id`, `client_order_ref`, `order_number`, `note`
- `delivery_address`, `installation_address`
- `has_deposit`, `deposit_amount`, `production_deadline`
- `order_lines` là mảng line API-friendly

Gửi các field workflow/internal như `order_state_custom`, `is_*_confirmed`, `production_group_ids` sẽ trả `400`.

Ví dụ:

```json
{
  "partner_id": 10,
  "conversation_id": 123,
  "user_id": 7,
  "client_order_ref": "WRITE-001",
  "order_number": "SO-WRITE-001",
  "note": "Created from API",
  "delivery_address": "123 API Street",
  "installation_address": "456 Builder Lane",
  "has_deposit": true,
  "deposit_amount": 250,
  "production_deadline": "2026-04-23",
  "order_lines": [
    {
      "product_id": 55,
      "quantity": 2,
      "price_unit": 3210,
      "tax_ids": [3]
    },
    {
      "display_type": "line_note",
      "name": "Customer note"
    }
  ]
}
```

#### 4.2 Update Order

**PATCH** `/dac_erp/api/v2/orders/<order_id>`

Rules:

- Partial update only
- `partner_id` và `conversation_id` là immutable sau khi tạo
- Nếu có `order_lines` thì bắt buộc có `line_mode=replace|patch`

`line_mode=replace`

- thay toàn bộ line editable
- giữ nguyên line hệ thống/đặt cọc

`line_mode=patch`

- `action=upsert`: update theo `id` hoặc create mới nếu không có `id`
- `action=delete`: bắt buộc có `id`, chỉ xóa line editable

Line schema:

| field | meaning |
|---|---|
| `id` | line hiện có khi patch |
| `product_id` | bắt buộc cho product line |
| `display_type` | `line_note` hoặc `line_section` cho display line |
| `name` | bắt buộc cho display line |
| `quantity` | map xuống `product_uom_qty` |
| `price_unit` | phải `>= 0` với product line; phải `0` với display line |
| `tax_ids` | mảng `account.tax` ids |
| `description`, `height`, `width` | field tùy chọn |
| `action` | chỉ dùng ở patch: `upsert|delete` |

Validation notes:

- Không cho tạo/sửa/xóa line âm tiền hoặc line deposit/system
- Không cho display line giả mạo deposit như “Khoản cọc”, “Tiền cọc”, `deposit`
- `delete` không được gửi kèm các field line khác ngoài `id` và `action`

Success response:

```json
{
  "success": true,
  "message": "Order updated successfully",
  "data": {
    "id": 1,
    "name": "S00001",
    "order_number": "SO-WRITE-001",
    "client_order_ref": "WRITE-001",
    "note": "Created from API",
    "delivery_address": "123 API Street",
    "installation_address": "456 Builder Lane",
    "production_deadline": "2026-04-23",
    "order_lines": [
      {
        "id": 10,
        "product_id": 55,
        "name": "API V2 Product",
        "description": null,
        "quantity": 2,
        "price_unit": 3210,
        "tax_ids": [3],
        "height": 0,
        "width": 0,
        "display_type": null
      }
    ]
  },
  "status_code": 200
}
```

Invalid payload examples:

```json
{
  "success": false,
  "message": "partner_id cannot be updated via this API",
  "error": "partner_id cannot be updated via this API",
  "status_code": 400
}
```

```json
{
  "success": false,
  "message": "Unauthorized: Invalid or missing X-API-KEY",
  "error": "Unauthorized: Invalid or missing X-API-KEY",
  "status_code": 401
}
```

## Error Response Format

```json
{
  "success": false,
  "error": "Error message",
  "timestamp": "2025-01-01T00:00:00",
  "status_code": 400
}
```

## Usage Examples

### 1. Get all data with date filter

```bash
curl -X GET "http(s)://<your-domain>/dac_erp/api/export/all?date_from=2025-01-01&date_to=2025-01-31" \
  -H "Cookie: session_id=your_session_id"
```

**Ví dụ cụ thể:**

```bash
# Development
curl -X GET "http://localhost:8069/dac_erp/api/export/all?date_from=2025-01-01&date_to=2025-01-31"

# Production
curl -X GET "https://crm.duyan.vn/dac_erp/api/export/all?date_from=2025-01-01&date_to=2025-01-31"
```

### 2. Get sales data with limit

```bash
curl -X GET "http(s)://<your-domain>/dac_erp/api/export/sales?limit=100" \
  -H "Cookie: session_id=your_session_id"
```

**Ví dụ cụ thể:**

```bash
# Development
curl -X GET "http://localhost:8069/dac_erp/api/export/sales?limit=100"

# Production
curl -X GET "https://crm.duyan.vn/dac_erp/api/export/sales?limit=100"
```

### 3. Get customers data

```bash
curl -X GET "http(s)://<your-domain>/dac_erp/api/export/customers" \
  -H "Cookie: session_id=your_session_id"
```

**Ví dụ cụ thể:**

```bash
# Development
curl -X GET "http://localhost:8069/dac_erp/api/export/customers"

# Production
curl -X GET "https://crm.duyan.vn/dac_erp/api/export/customers"
```

## Features

### Custom Fields Support

- API tự động detect và include các custom fields như:
  - `order_state_custom` trong sale.order
  - `dac_deposit_invoice` trong account.move
  - `is_deposit_payment`, `is_final_payment` trong account.payment

### Relationship Handling

- Many2one fields được serialize thành object với id và name
- One2many/Many2many fields được serialize thành array of objects
- Date/Datetime fields được format theo ISO 8601

### Performance Optimization

- Default limit để tránh timeout
- Lazy loading cho relationship fields
- Efficient domain filtering

### Error Handling

- Comprehensive error logging
- User-friendly error messages
- Proper HTTP status codes

## Security Notes

- Yêu cầu authentication
- Chỉ trả về dữ liệu user có quyền truy cập
- No CSRF protection (API dành cho internal use)

## Integration Examples

### Python

```python
import requests

# Cấu hình domain
BASE_URL = "http(s)://<your-domain>"  # Thay đổi theo môi trường
# BASE_URL = "http://localhost:8069"  # Development
# BASE_URL = "https://crm.duyan.vn"   # Production

session = requests.Session()

# Login first
login_data = {
    'login': 'admin',
    'password': 'admin',
    'db': 'your_db'
}
session.post(f'{BASE_URL}/web/login', data=login_data)

# Get data
response = session.get(f'{BASE_URL}/dac_erp/api/export/all')
data = response.json()

# Ví dụ: Get sales data với filter
response = session.get(
    f'{BASE_URL}/dac_erp/api/export/sales',
    params={'date_from': '2025-01-01', 'date_to': '2025-01-31', 'limit': 100}
)
sales_data = response.json()
```

### JavaScript

```javascript
// Sử dụng relative path (tự động dùng domain hiện tại)
fetch("/dac_erp/api/export/sales?limit=50")
  .then((response) => response.json())
  .then((data) => {
    console.log("Sales data:", data);
  });

// Hoặc dùng absolute URL với domain cụ thể
const BASE_URL = "http(s)://<your-domain>"; // Thay đổi theo môi trường
// const BASE_URL = "http://localhost:8069";  // Development
// const BASE_URL = "https://crm.duyan.vn";   // Production

fetch(`${BASE_URL}/dac_erp/api/export/sales?limit=50&date_from=2025-01-01`)
  .then((response) => response.json())
  .then((data) => {
    console.log("Sales data:", data);
    console.log("Total items:", data.count);
  })
  .catch((error) => console.error("Error:", error));
```

## API v2 Read Filters For OpenClaw

### Conversations

Canonical route:

- `GET /dac_erp/api/v2/conversations`

Useful filters:

- `conversation_id`
- `page_id`
- `page_fm_id_str`
- `platform`
- `status`
- `require_processing`
- `has_unread`
- `is_internal`
- `owner_id`
- `participant_id`
- `assignee_user_id`
- `date`
- `date_from`
- `date_to`
- `date_field=updated_at_fm|last_message_at_fm`
- `days`
- `unreplied`
- `unreplied_date`
- `unreplied_date_from`
- `unreplied_date_to`
- `staff_user_id`
- `tag_code`
- `tag_mode=any|all`

### Messages

Canonical route:

- `GET /dac_erp/api/v2/messages`

Useful filters:

- `conversation_id`
- `conversation_fm_id`
- `page_id`
- `page_fm_id_str`
- `staff_user_id`
- `assignee_user_id`
- `sender_role=customer|staff|system|unknown`
- `type_content`
- `platform`
- `tag_code`
- `date`
- `date_from`
- `date_to`
- `conversation_unreplied`

## API v3 AI Write APIs

Base URL:

```text
http(s)://<your-domain>/dac_erp/api/v3/
```

Authentication:

- Header: `X-API-KEY`
- System parameter: `dac_erp.api_v3_ai_write_key`

Idempotency:

- Every write request must include `request_id`
- Reusing the same `request_id` with the same payload returns a replayed response
- Reusing the same `request_id` with a different payload returns `409`

### 1. AI Summary

**POST** `/dac_erp/api/v3/conversations/<id>/ai-summary`

```json
{
  "request_id": "oclaw-001",
  "agent_name": "OpenClaw",
  "model_name": "gpt-5",
  "summary_text": "Khach dang cho phan hoi ve tien do giao hang",
  "reason": "customer_follow_up",
  "confidence": 0.91
}
```

### 2. AI Note

**POST** `/dac_erp/api/v3/conversations/<id>/ai-note`

```json
{
  "request_id": "oclaw-002",
  "agent_name": "OpenClaw",
  "model_name": "gpt-5",
  "note_text": "Khach co dau hieu sot ruot, can theo doi sat",
  "note_type": "internal_note"
}
```

### 3. Follow-up Activity

**POST** `/dac_erp/api/v3/conversations/<id>/activities`

```json
{
  "request_id": "oclaw-003",
  "agent_name": "OpenClaw",
  "model_name": "gpt-5",
  "summary": "Goi lai khach de cap nhat lich giao hang",
  "note": "Tin nhan moi nhat cua khach chua duoc phan hoi",
  "user_id": 17,
  "deadline_date": "2026-04-29"
}
```

### 4. Triage Update

**PATCH** `/dac_erp/api/v3/conversations/<id>/triage`

```json
{
  "request_id": "oclaw-004",
  "agent_name": "OpenClaw",
  "model_name": "gpt-5",
  "status_state": "recontact",
  "require_processing": true,
  "mark_read": true,
  "reason": "customer_waiting_for_reply"
}
```

### 5. Tag Replace

**PUT** `/dac_erp/api/v3/conversations/<id>/tags`

```json
{
  "request_id": "oclaw-005",
  "agent_name": "OpenClaw",
  "model_name": "gpt-5",
  "tag_codes": ["CONSULTING", "VIP"],
  "reason": "conversation_tagging"
}
```

Tag write notes:

- Tags are selected by `page.fm.tag.odoo_tag_code`
- Tag sync is immediate against Pancake
- Tag write does not automatically change `status_state` or `require_processing`

### Response shape

```json
{
  "success": true,
  "message": "Conversation tags updated successfully",
  "status_code": 200,
  "data": {
    "conversation_id": 123,
    "log_id": 456,
    "idempotent_replay": false,
    "changed_fields": {},
    "conversation": {
      "id": 123,
      "conversation_fm_id": "conv_abc",
      "status_state": "recontact",
      "require_processing": true,
      "is_unread": false,
      "last_suggestion_at": "2026-04-29T08:15:00",
      "suggestion_note": "..."
    }
  }
}
```
