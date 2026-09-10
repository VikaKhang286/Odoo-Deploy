# DuyAn CRM - Hệ thống Quản lý Khách hàng & ERP

## 📋 Tổng quan hệ thống

Hệ thống DuyAn CRM là một giải pháp quản lý khách hàng và ERP tích hợp hoàn chỉnh được xây dựng trên nền tảng Odoo 18.0, được thiết kế đặc biệt cho Duy An Company. Hệ thống bao gồm 5 module chính tương tác với nhau để tạo nên một hệ sinh thái quản lý doanh nghiệp đầy đủ.

## 🏗️ Kiến trúc hệ thống

```
📁 addons/
├── 🎨 Chameleon/           # Theme & UI Customization
├── 🤝 CRM_DAC/             # Customer Relationship Management
├── 💼 dac_erp/             # Enterprise Resource Planning
├── 📊 dac_report/          # Dashboard & Reports
└── 🏠 home_menu/           # Home Menu & Navigation
```

## 📦 Module Chi tiết

### 🎨 Chameleon - Theme & UI Customization

**Mục đích:** Tùy chỉnh giao diện và theme cho hệ thống

**Chức năng chính:**

- Thay đổi màu sắc theme theo sở thích
- Tùy chỉnh giao diện người dùng
- Cung cấp các template giao diện tùy biến

**Cấu trúc:**

```
Chameleon/
├── models/
│   └── resConfigSettings.py          # Cấu hình theme settings
├── views/
│   ├── Chameleon.xml                 # Main theme views
│   ├── ChangeColorTheme.xml          # Color customization UI
│   ├── course_list_template.xml      # Course list templates
│   └── ResConfigSettings.xml         # Settings configuration views
├── static/
│   ├── description/                  # Module description & icons
│   └── src/                         # CSS, JS, Images resources
└── security/
    └── ir.model.access.csv          # Access rights
```

**Dependencies:** `base`, `web`

---

### 🤝 CRM_DAC - Customer Relationship Management

**Mục đích:** Quản lý cuộc trò chuyện khách hàng và đồng bộ dữ liệu từ Pancake.vn

**Chức năng chính:**

- 🔄 **Đồng bộ hội thoại**: Tự động đồng bộ cuộc trò chuyện từ Pancake.vn (Zalo, Facebook, Instagram)
- 💬 **Quản lý tin nhắn**: Hiển thị và quản lý tin nhắn chi tiết từ nhiều kênh
- 👥 **Quản lý khách hàng**: Liên kết conversations với partner records, tự động tạo/cập nhật khách hàng
- 📈 **KPI tracking**: Theo dõi hiệu suất nhân viên bán hàng theo ngày/tháng
- 🔔 **Workflow management**: Quản lý trạng thái xử lý cuộc hội thoại (New, Processing, Resolved)
- 🏷️ **Tag Management**: Phân loại conversations bằng tags

**Models chính:**

- `page.fm.page`: Quản lý Pages từ Pancake (Zalo OA, Facebook Page)
- `page.fm.conversation`: Cuộc trò chuyện khách hàng với workflow states
- `page.fm.message`: Tin nhắn chi tiết (text, image, file attachments)
- `page.fm.tag`: Tags để phân loại conversations
- `kpi.sale.daily`: KPI hàng ngày của nhân viên sale
- `res.partner` (extended): Liên kết với Pancake conversations
- `res.users` (extended): Pancake access tokens và permissions

**Cấu trúc:**

```
CRM_DAC/
├── models/
│   ├── page_fm_models.py                    # Page management & sync
│   ├── page_fm_conversation_models.py       # Conversation logic & workflow
│   ├── page_fm_message_models.py           # Message handling & sync
│   ├── page_fm_tag.py                      # Tag management
│   ├── kpi_sale_daily.py                   # KPI calculations & reporting
│   └── res_ext.py                          # Partner/User extensions
├── controllers/
│   └── main.py                             # Web controllers & API endpoints
├── views/
│   ├── page_fm_conversation_views.xml      # Conversation list/form/kanban views
│   ├── page_fm_page_views.xml              # Page management UI
│   ├── page_fm_tag_view.xml                # Tag configuration
│   ├── KPI_View.xml                        # KPI dashboard views
│   ├── res_partner_views_inherit_pancake.xml  # Partner extensions
│   ├── res_users_views_inherit_pancake.xml    # User extensions
│   └── menuitem.xml                        # Menu structure
├── wizard/
│   └── conversation_message_sync_wizard.py # Manual sync wizard
├── data/
│   └── cron_pancake.xml                    # Scheduled jobs (auto-sync)
└── security/
    ├── ir.model.access.csv                 # Model access rights
    └── user_access_rule.xml                # Record rules per user
```

**API Integration:**

- **Pancake.vn REST API**: Đồng bộ conversations, messages, pages
- **Webhook receivers**: Real-time updates khi có tin nhắn mới
- **Token management**: Secure token storage và refresh
- **Rate limiting**: Xử lý API rate limits

**Cron Jobs:**

- Auto-sync conversations mỗi 15 phút
- Auto-sync messages cho conversations active
- KPI calculation hàng ngày

**Dependencies:** `base`, `web`, `dac_erp`, `home_menu`

---

### 💼 dac_erp - Enterprise Resource Planning

**Mục đích:** Core ERP functionality cho quản lý bán hàng, kế toán, sản xuất và sản phẩm

**Chức năng chính:**

- 📋 **Quản lý đơn hàng**: Custom workflow đơn hàng (Quotation → Production → Delivery → Installation → Payment → Completed)
- 💰 **Quản lý thanh toán**: Tracking payments, deposits, receivables với nhiều phương thức thanh toán
- 🎨 **Design Dashboard**: Dashboard cho team thiết kế theo dõi công việc
- 📊 **Data Export API**: RESTful API để export toàn bộ dữ liệu hệ thống
- 🔗 **Webhook Integration**: Nhận webhook từ Pancake và các hệ thống external
- 👤 **User Management**: Phân quyền chi tiết theo vai trò (Manager, Sale, Design, Production)
- 📦 **Product Management**: Quản lý sản phẩm, variant, pricing với custom fields
- 🔐 **Debug Guard**: Security layer chặn debug mode cho non-admin users
- 💵 **Multi-currency**: Hỗ trợ VND và USD với tỷ giá tự động

**Models chính:**

- `sale.order` (extended): Custom workflow states, team assignment, conversation linking
- `sale.order.line` (extended): Product details, pricing calculations
- `account.move` (extended): Invoice với deposit tracking
- `account.payment` (extended): Payment methods, reconciliation
- `account.payment.register` (extended): Payment registration wizard
- `product.template` (extended): Custom product fields
- `design.dashboard`: Dashboard data cho team design
- `deposit.confirm.wizard`: Wizard xác nhận đặt cọc

**Workflow States:**

```
                    ┌─────────────┐
                    │  Quotation  │
                    └──────┬──────┘
                           │
                ┌──────────┴──────────┐
                │                     │
                ↓                     ↓
         ┌────────────┐          ┌────────┐
         │   Deposit  │          │ Cancel │
         │  + Design  │          └────────┘
         └──────┬─────┘
                │
                ↓
         ┌────────────┐
         │ Production │
         └──────┬─────┘
                │
        ┌───────┴───────┐
        │               │
        ↓               ↓
   ┌─────────┐    ┌──────────────┐
   │Delivery │    │ Installation │
   └────┬────┘    └──────┬───────┘
        │                │
        └────────┬───────┘
                 │
                 ↓
           ┌─────────┐
           │ Payment │
           └────┬────┘
                │
                ↓
           ┌───────────┐
           │ Completed │
           └───────────┘

Các trạng thái chi tiết:
- Quotation: Draft / Sent / Confirmed
- Deposit & Design: Deposit Paid / Design Approved / Waiting for Production
- Production: In Production / QC Check
- Delivery: Ready for Delivery / Delivered (nhánh 1)
- Installation: Ready for Installation / Installed (nhánh 2)
- Payment: Invoiced / Partially Paid / Fully Paid
- Completed: Order Completed
- Cancel: Cancelled (từ Quotation)
```

**Cấu trúc:**

```
dac_erp/
├── models/
│   ├── sale_order.py                       # Main order logic & workflow
│   ├── sale_order_line_inherit.py          # Order line extensions
│   ├── account_move.py                     # Invoice & deposit handling
│   ├── account_payment.py                  # Payment processing
│   ├── account_payment_register.py         # Payment registration
│   ├── product_template_inherit.py         # Product custom fields
│   ├── design_dashboard.py                 # Design team dashboard
│   └── deposit_confirm_wizard.py           # Deposit confirmation wizard
├── controllers/
│   ├── data_export_controller.py           # REST API for data export
│   ├── pancake_webhook_controller.py       # Webhook receivers
│   └── debug_guard.py                      # Security controller
├── views/
│   ├── sale_order_view.xml                 # Main order form/list/kanban
│   ├── sale_order_design_view.xml          # Design team views
│   ├── account_move_view.xml               # Invoice views
│   ├── account_move_deposit_view.xml       # Deposit invoice views
│   ├── account_payment_view.xml            # Payment views
│   ├── deposit_confirm_wizard_view.xml     # Deposit wizard
│   ├── design_dashboard_action.xml         # Dashboard actions
│   ├── res_partner_views.xml               # Customer form extensions
│   ├── res_users_views.xml                 # User form extensions
│   └── menuitem.xml                        # Menu structure
├── security/
│   ├── user_access.xml                     # User groups definition
│   ├── sale_order_access_rules.xml         # Order access rules by role
│   ├── account_access_rules.xml            # Accounting access rules
│   └── ir.model.access.csv                 # Model-level permissions
├── data/
│   ├── currency_data.xml                   # VND & USD setup
│   └── cron_data.xml                       # Scheduled jobs
├── report/
│   └── account_report_invoice_inherit.xml  # Custom invoice reports
└── static/src/
    ├── js/backend/
    │   └── conversation_widget.js          # Conversation widget on orders
    ├── css/backend/
    │   ├── sale_order_form.css             # Order form styling
    │   └── conversation_widget.css         # Widget styling
    └── xml/backend/
        └── templates.xml                   # QWeb templates
```

**API Endpoints:**

- `GET /api/export/all` - Export tất cả dữ liệu
- `GET /api/export/sales` - Export đơn hàng
- `GET /api/export/customers` - Export khách hàng
- `GET /api/export/invoices` - Export hóa đơn
- `GET /api/export/payments` - Export thanh toán
- `GET /api/export/products` - Export sản phẩm
- `POST /webhook/pancake` - Webhook từ Pancake

**User Groups:**

- `group_dac_erp_manager`: Full access, dashboard quản lý
- `group_dac_erp_sale`: Quản lý đơn hàng, khách hàng
- `group_dac_erp_design`: Dashboard thiết kế, đơn hàng assigned
- `group_dac_erp_production`: Xem đơn sản xuất

**Security Features:**

- Debug Guard: Chặn debug mode cho non-admin
- Role-based access control
- Record-level permissions
- Secure API with authentication

**Dependencies:** `base`, `web`, `home_menu`, `Chameleon`, `sale`, `sale_management`, `account`, `product`

---

### 📊 dac_report - Dashboard & Reports

**Mục đích:** Báo cáo và dashboard theo dõi hiệu suất kinh doanh real-time

**Chức năng chính:**

- 📈 **Sales Dashboard**: Dashboard tổng quan doanh thu và KPI với interactive widgets
- 🎯 **Target Tracking**: Theo dõi mục tiêu doanh thu theo tháng/quý
- 👥 **Customer Analytics**: Phân tích khách hàng và conversion funnel
- 📊 **Real-time Reporting**: Báo cáo thời gian thực với auto-refresh
- 🔄 **Interactive UI**: Giao diện tương tác với OWL components
- 📱 **Responsive Design**: Tương thích mobile và tablet

**Dashboard Components:**

- **Header KPIs**:
  - Doanh thu tháng hiện tại
  - Mục tiêu doanh thu
  - Progress percentage
  - Growth rate
- **Consulting Pipeline**: Danh sách khách hàng đang tư vấn (quotation stage)
- **Quotation Tracking**: Đơn hàng đã báo giá chưa confirm
- **Manufacturing Status**: Trạng thái đơn hàng đang sản xuất
- **Receivables**: Công nợ cần thu theo khách hàng
- **Completed Orders**: Đơn hàng đã hoàn thành trong tháng

**Cấu trúc:**

```
dac_report/
├── models/
│   └── dashboard.py                        # Dashboard data logic & calculations
├── controllers/
│   └── dashboard_controller.py             # API endpoints for dashboard
├── static/src/
│   ├── js/backend/
│   │   └── dashboard.js                    # OWL components & frontend logic
│   ├── css/backend/
│   │   └── dac_report.css                  # Dashboard custom styling
│   └── xml/backend/
│       └── sale_dashboard.xml              # QWeb templates for widgets
├── views/
│   └── menuitem.xml                        # Menu definitions & actions
└── security/
    └── ir.model.access.csv                 # Dashboard access rights
```

**Technical Features:**

- **OWL Framework**: Modern reactive components
- **Real-time Data**: Auto-refresh every 5 minutes
- **Responsive Grid**: CSS Grid layout for mobile
- **Custom Styling**: Branded color scheme
- **Action Integration**: Click-through to detailed views
- **Export Functions**: Excel/PDF export capabilities

**KPIs Tracked:**

- Revenue metrics (current, target, growth)
- Conversion rates (quote → order)
- Average order value
- Customer acquisition cost
- Sales cycle duration
- Team performance metrics

**Dependencies:** `base`, `web`, `dac_erp`, `CRM_DAC`, `sale`, `account`, `sale_management`, `product`

---

### 🏠 home_menu - Home Menu & Navigation

**Mục đích:** Tùy chỉnh menu chính, navigation và user experience

**Chức năng chính:**

- 🧭 **Custom Menu Structure**: Tùy chỉnh menu tree theo role
- 🔗 **Smart Navigation**: Redirect users về menu phù hợp khi login
- 🎨 **Home Page Customization**: Custom home page theo user group
- 📱 **Mobile-friendly Navigation**: Responsive menu cho mobile devices
- 👤 **User Context**: Lưu trữ navigation preferences

**Key Features:**

- Auto-redirect based on user group
- Custom navbar với webclient patches
- Home button functionality
- Menu blocking for specific roles

**Cấu trúc:**

```
home_menu/
├── models/
│   └── home_menu.py                        # Menu model & logic
├── static/src/
│   ├── js/backend/
│   │   ├── web_client.js                   # WebClient patches for routing
│   │   ├── navbar.js                       # Navbar customization
│   │   └── custom_user_item.js             # User menu items
│   └── xml/backend/
│       └── navbar.xml                      # Navbar QWeb templates
├── views/
│   ├── home_menu.xml                       # Home menu structure
│   └── menu_item.xml                       # Menu item definitions
└── security/
    └── ir.model.access.csv                 # Access rights
```

**User Routing Logic:**

```javascript
base.group_system → Default Odoo behavior
dac_erp.group_dac_erp_manager → dac_report.dac_sale_dashboard
dac_erp.group_dac_erp_sale → dac_report.dac_sale_dashboard
dac_erp.group_dac_erp_design → dac_erp.dac_design_root_menu
Others → home_menu.home_root
```

**Dependencies:** `base`, `web`

---

## 🔗 Mối quan hệ giữa các Module

```
home_menu (Base Navigation)
    ↓
Chameleon (UI Theme)
    ↓
dac_erp (Core ERP)
    ↓
    ├──→ CRM_DAC (Customer Management)
    └──→ dac_report (Analytics & Dashboard)
```

**Data Flow:**

```
External Sources (Pancake, Webhooks)
    ↓
CRM_DAC (Conversations & Leads)
    ↓
dac_erp (Sales Orders & Workflow)
    ↓
dac_report (Analytics & KPIs)
    ↓
Users (Dashboard & Actions)
```

## 🚀 Workflow Hoạt động

### 1. Customer Journey

```
Pancake.vn → CRM_DAC → dac_erp → dac_report
     ↓           ↓         ↓          ↓
Messages → Conversations → Orders → Analytics
     ↓           ↓         ↓          ↓
Social → Leads/Opps → Sales → KPIs
```

### 2. Sales Process

```
1. Conversation (Pancake) → Assign to Sales
2. Create Quotation → Design Team
3. Design Approval → Production
4. Manufacturing → QC → Delivery
5. Installation (if needed) → Payment
6. Invoice → Complete → Analytics
```

### 3. Data Synchronization

```
Every 15 minutes:
- Sync new conversations from Pancake
- Sync messages for active conversations
- Update partner information
- Calculate daily KPIs
```

## 🔧 Cài đặt & Cấu hình

### Thứ tự cài đặt modules:

1. `home_menu` - Base navigation system
2. `Chameleon` - Theme foundation
3. `dac_erp` - Core ERP functionality
4. `CRM_DAC` - CRM và Pancake integration
5. `dac_report` - Dashboards và analytics

### Cấu hình cần thiết:

#### 1. Pancake.vn API Setup

```
Settings → CRM_DAC → Pancake Configuration
- Access Token: [Your Pancake Token]
- Webhook URL: https://yourdomain.com/webhook/pancake
- Auto-sync interval: 15 minutes (default)
```

#### 2. User Groups & Permissions

```
Settings → Users & Companies → Groups
- DAC Manager: Full system access
- DAC Sale: Sales & customer management
- DAC Design: Design dashboard & assigned orders
- DAC Production: Production orders view
```

#### 3. Currency Configuration

```
Accounting → Configuration → Currencies
- VND: Active, Rate = 1
- USD: Active, Rate = auto-update
```

#### 4. Cron Jobs Setup

```
Settings → Technical → Scheduled Actions
✓ CRM_DAC: Auto-sync Conversations (every 15 min)
✓ CRM_DAC: Auto-sync Messages (every 10 min)
✓ CRM_DAC: Daily KPI Calculation (daily 00:00)
✓ dac_erp: Currency Rate Update (daily)
```

#### 5. Webhook Configuration

- Configure webhook URL trong Pancake dashboard
- Test webhook connectivity
- Monitor webhook logs

## 📊 Key Features Summary

### 🤖 Automation

- ✅ Tự động đồng bộ conversations từ social platforms (Zalo, Facebook)
- ✅ Auto-assign conversations cho sales teams theo rules
- ✅ Scheduled data synchronization (conversations, messages, KPIs)
- ✅ Automated KPI calculations và reporting
- ✅ Auto-create customers từ Pancake conversations
- ✅ Currency rate auto-update

### 🔐 Security

- ✅ Role-based access control (Manager, Sale, Design, Production)
- ✅ Multi-level user permissions (model + record level)
- ✅ Data isolation theo team/department
- ✅ Secure API endpoints với authentication
- ✅ Debug Guard - chặn debug mode cho non-admin
- ✅ Secure webhook handling với validation

### 📱 User Experience

- ✅ Responsive dashboard design (desktop, tablet, mobile)
- ✅ Real-time notifications và updates
- ✅ Interactive conversation management
- ✅ Drag-and-drop conversation widget trên sale orders
- ✅ Bubble mode cho conversation widget
- ✅ Keyboard shortcuts (Ctrl+Shift+C, Ctrl+Shift+X)
- ✅ Smart positioning với edge snapping

### 🔌 Integration

- ✅ Pancake.vn API integration (full-featured)
- ✅ RESTful data export APIs
- ✅ Webhook support (inbound/outbound)
- ✅ External system connectivity
- ✅ Multi-currency support

## 🛠️ Technical Stack

- **Backend**: Odoo 18.0 (Python 3.10+)
- **Frontend**: OWL Framework, JavaScript ES6+, CSS3
- **Database**: PostgreSQL 17
- **API**: REST, Webhooks, JSON
- **Integration**: Pancake.vn API v2
- **Deployment**: Docker Compose
- **Web Server**: Nginx (optional)

## 📈 Metrics & KPIs

### Sales Metrics

- Revenue (actual vs target)
- Conversion rates (quote → order)
- Average order value
- Sales pipeline value
- Win rate percentage

### Customer Metrics

- Response time to conversations
- Customer satisfaction scores
- Customer retention rate
- New customer acquisition

### Employee Metrics

- Individual sales performance
- Productivity metrics
- Target achievement
- Response time

### Operational Metrics

- Order cycle time
- Process efficiency
- Data accuracy
- System uptime

## 🚀 Roadmap

### Phase 1 (Completed)

- ✅ Core ERP functionality
- ✅ Pancake.vn integration
- ✅ Sales dashboard
- ✅ User management

### Phase 2 (In Progress)

- 🔄 AI-powered conversation analysis
- 🔄 Advanced reporting và analytics
- 🔄 Mobile app development
- 🔄 WhatsApp integration

### Phase 3 (Planned)

- 📋 Additional social platform integrations
- 📋 Enhanced automation workflows
- 📋 Predictive analytics
- 📋 Customer portal

## 🐛 Troubleshooting

### Common Issues

**1. Pancake sync không hoạt động**

- Check access token validity
- Verify cron job đang chạy
- Check API rate limits
- Review error logs

**2. Dashboard không load**

- Clear browser cache
- Check user permissions
- Verify module installed correctly
- Restart Odoo service

**3. Webhook không nhận**

- Verify webhook URL accessible
- Check firewall settings
- Test webhook endpoint manually
- Review nginx/proxy configuration

**4. Debug mode bị chặn**

- Đúng behavior cho non-admin users
- Admin users vẫn access được
- Check debug_guard controller logs

## 📞 Support

**Tác giả**: Huỳnh Quốc An  
**Email**: anhuynh.110301@gmail.com  
**Phiên bản**: 1.0  
**Cập nhật**: October 2025  
**Công ty**: Duy An Company

---

## 📄 License

LGPL-3 License - See LICENSE file for details
