# DAC ERP - Data Export API Documentation

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
