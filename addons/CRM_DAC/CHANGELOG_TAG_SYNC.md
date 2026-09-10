# 🔄 CHANGELOG: Đồng bộ Tag từ Pancake về Odoo

## 📅 Ngày: 2025-10-29

---

## 🎯 MỤC TIÊU

Xây dựng tính năng **đồng bộ tags từ Pancake về Odoo** cho cả Conversation và Customer/Partner, tự động khi:

1. Fetch conversations từ API
2. Sync messages thành công
3. Thủ công qua button/action

---

## ✅ NHỮNG GÌ ĐÃ LÀM

### 1️⃣ **Cập nhật Model `res.partner`**

**File:** `models/res_ext.py`

**Thêm mới:**

```python
# Field để lưu tags từ Pancake
pancake_tag_ids = fields.Many2many(
    'page.fm.tag',
    'res_partner_pancake_tag_rel',
    'partner_id',
    'tag_id',
    string="Thẻ từ Pancake",
    help="Tags được đồng bộ từ conversation mới nhất trên Pancake"
)

# Hàm đồng bộ tags từ conversation mới nhất
def sync_tags_from_conversations(self):
    """Đồng bộ tags từ conversation mới nhất sang khách hàng."""
    Conv = self.env['page.fm.conversation'].sudo()
    for partner in self:
        # Lấy conversation mới nhất có tags
        conv = Conv.search(
            [('partner_id', '=', partner.id), ('pancake_tag_ids', '!=', False)],
            order='updated_at_fm desc, id desc', limit=1
        )
        if conv and conv.pancake_tag_ids:
            partner.write({
                'pancake_tag_ids': [(6, 0, conv.pancake_tag_ids.ids)]
            })
```

---

### 2️⃣ **Cập nhật Fetch Conversations**

**File:** `models/page_fm_models.py`

**a) Lấy tag_ids từ API:**

```python
# Trong _fetch_conversations_for_page_record()
# 🆕 Lấy tags từ API (nếu có)
api_tag_ids = conv_data.get('tag_ids', []) or []
if not isinstance(api_tag_ids, list):
    api_tag_ids = []

processed_conv = {
    # ... các field khác ...
    'api_tag_ids': api_tag_ids,  # 🆕 Truyền tag_ids từ API
}
```

**b) Map tags và sync sang partner:**

```python
# Trong _create_or_update_conversations()
def _create_or_update_conversations(self, conversations_data_list):
    # ...
    for conv_vals in conversations_data_list:
        # 🆕 Lấy api_tag_ids trước khi xử lý
        api_tag_ids = conv_vals.pop('api_tag_ids', [])

        # 🆕 Map tag_ids từ Pancake sang Odoo tags
        odoo_tag_ids = []
        if api_tag_ids:
            for tag_id_str in api_tag_ids:
                tag = TagEnv.search([
                    ('tag_fm_id', '=', str(tag_id_str)),
                    ('page_id', '=', self.id)
                ], limit=1)
                if tag:
                    odoo_tag_ids.append(tag.id)

        # Gán tags vào conversation
        if odoo_tag_ids:
            conv_vals['pancake_tag_ids'] = [(6, 0, odoo_tag_ids)]

        if existing_conv:
            existing_conv.write(conv_vals)

            # 🆕 Sync tags sang partner nếu có
            if existing_conv.partner_id and odoo_tag_ids:
                existing_conv.partner_id.sudo().write({
                    'pancake_tag_ids': [(6, 0, odoo_tag_ids)]
                })
        else:
            new_conv = ConversationEnv.create(conv_vals)

            # 🆕 Sync tags sang partner nếu có
            if new_conv.partner_id and odoo_tag_ids:
                new_conv.partner_id.sudo().write({
                    'pancake_tag_ids': [(6, 0, odoo_tag_ids)]
                })
```

---

### 3️⃣ **Cập nhật Sync Messages**

**File:** `models/page_fm_conversation_models.py`

**a) Thêm hàm tiện ích:**

```python
def sync_tags_to_partner(self):
    """🆕 Đồng bộ tags từ conversation sang partner"""
    for record in self:
        if record.partner_id and record.pancake_tag_ids:
            try:
                record.partner_id.sudo().write({
                    'pancake_tag_ids': [(6, 0, record.pancake_tag_ids.ids)]
                })
                _logger.info(f"✅ Synced {len(record.pancake_tag_ids)} tags to partner {record.partner_id.name}")
            except Exception as e:
                _logger.error(f"Lỗi sync tags to partner: {e}", exc_info=True)
```

**b) Auto sync sau khi sync messages thành công:**

```python
# Trong action_sync_messages()
# 🆕 Đồng bộ tags từ conversation sang partner (nếu có)
try:
    if record.partner_id and record.pancake_tag_ids:
        record.partner_id.sudo().write({
            'pancake_tag_ids': [(6, 0, record.pancake_tag_ids.ids)]
        })
        _logger.info(f"✅ Synced {len(record.pancake_tag_ids)} tags from conversation to partner {record.partner_id.name} after message sync")
except Exception as e:
    _logger.error(f"Lỗi khi sync tags sang partner: {e}", exc_info=True)
```

---

### 4️⃣ **Cập nhật View Partner**

**File:** `views/res_partner_views_inherit_pancake.xml`

**Thêm group hiển thị tags:**

```xml
<group string="Thẻ từ Pancake" name="pancake_tags_group">
    <field name="pancake_tag_ids"
           widget="many2many_tags"
           options="{'color_field': 'color', 'no_create_edit': True}"
           placeholder="Tags được đồng bộ từ conversation"/>
</group>
```

---

## 🔄 FLOW HOẠT ĐỘNG

### **Kịch bản 1: Fetch Conversations**

```
1. User click "Sync Conversations" trên Page
   ↓
2. API Pancake trả về conversations với tag_ids: [23, 25, 31]
   ↓
3. System map tag_ids → page.fm.tag (Odoo)
   ↓
4. Gán vào conversation.pancake_tag_ids
   ↓
5. Nếu conversation.partner_id tồn tại
   → Auto sync tags sang partner.pancake_tag_ids
```

### **Kịch bản 2: Sync Messages**

```
1. User click "Sync Messages" trên Conversation
   ↓
2. Messages được sync thành công
   ↓
3. Kiểm tra conversation.pancake_tag_ids
   ↓
4. Nếu có tags và có partner
   → Auto sync tags sang partner.pancake_tag_ids
```

### **Kịch bản 3: Sync thủ công**

```python
# Từ conversation
conversation.sync_tags_to_partner()

# Từ partner
partner.sync_tags_from_conversations()
```

---

## 📊 DỮ LIỆU MẪU

### **Trước khi sync:**

```python
# Conversation
conversation.pancake_tag_ids = []
conversation.partner_id.pancake_tag_ids = []

# API Response
{
    "id": "conv_123",
    "tag_ids": [23, 25, 31],  # Đang thiết kế, Chưa thu tiền, Done
    ...
}
```

### **Sau khi sync:**

```python
# Conversation
conversation.pancake_tag_ids = [
    page.fm.tag(23, "Đang thiết kế"),
    page.fm.tag(25, "Chưa thu tiền"),
    page.fm.tag(31, "Done")
]

# Partner (auto sync)
partner.pancake_tag_ids = [
    page.fm.tag(23, "Đang thiết kế"),
    page.fm.tag(25, "Chưa thu tiền"),
    page.fm.tag(31, "Done")
]
```

---

## 🎯 LỢI ÍCH

### ✅ **Cho User:**

1. Nhìn tags của khách hàng ngay trên form Partner
2. Không cần mở Conversation để xem tags
3. Tags luôn cập nhật theo conversation mới nhất

### ✅ **Cho System:**

1. Đồng bộ 2 chiều hoàn chỉnh:
   - Odoo → Pancake (đã có)
   - Pancake → Odoo (mới)
2. Tự động hóa 100% - không cần thao tác thủ công
3. Log đầy đủ để debug

### ✅ **Cho Developer:**

1. Code sạch, dễ maintain
2. Tách biệt logic rõ ràng
3. Có hàm tiện ích để tái sử dụng

---

## 🐛 KNOWN ISSUES & LIMITATIONS

### ⚠️ **API Pancake limitations:**

- Không có endpoint GET tags của 1 conversation cụ thể
- Endpoint conversations chỉ dùng `tags` parameter để FILTER
- Phải rely vào `tag_ids` trong response khi fetch list

### ⚠️ **Giải pháp:**

- Sync định kỳ để cập nhật tags mới nhất
- Manager có thể sửa tags thủ công trên conversation
- Auto sync lên Pancake khi save

---

## 📝 TESTING

### **Test Case 1: Fetch conversations với tags**

```python
# 1. Tạo tags trước
env['page.fm.tag'].action_sync_page_tags()

# 2. Fetch conversations
page.action_sync_specific_pages_conversations()

# 3. Kiểm tra
conv = env['page.fm.conversation'].search([], limit=1)
assert len(conv.pancake_tag_ids) > 0
assert len(conv.partner_id.pancake_tag_ids) > 0
```

### **Test Case 2: Sync messages tự động sync tags**

```python
# 1. Conversation có tags nhưng partner chưa
conv.partner_id.write({'pancake_tag_ids': [(5, 0, 0)]})

# 2. Sync messages
conv.action_sync_messages()

# 3. Kiểm tra
assert conv.partner_id.pancake_tag_ids == conv.pancake_tag_ids
```

### **Test Case 3: Sync thủ công**

```python
# 1. Partner chưa có tags
partner.pancake_tag_ids = []

# 2. Sync từ conversation
partner.sync_tags_from_conversations()

# 3. Kiểm tra
latest_conv = env['page.fm.conversation'].search([
    ('partner_id', '=', partner.id),
    ('pancake_tag_ids', '!=', False)
], order='updated_at_fm desc', limit=1)
assert partner.pancake_tag_ids == latest_conv.pancake_tag_ids
```

---

## 🚀 DEPLOYMENT

### **Bước 1: Update module**

```bash
# Trong Odoo
Apps → CRM_DAC → Upgrade
```

### **Bước 2: Sync tags**

```
Menu → Pages.fm → Pages → Sync Tags
```

### **Bước 3: Re-sync conversations**

```
Menu → Pages.fm → Pages → Sync Conversations
```

### **Bước 4: Verify**

```
Menu → Contacts → Mở customer → Kiểm tra "Thẻ từ Pancake"
```

---

## 📚 TÀI LIỆU THAM KHẢO

1. **Hướng dẫn chi tiết:** `doc/HUONG_DAN_DONG_BO_TAG_PANCAKE.md`
2. **API Documentation:** `API_DOCUMENTATION.md`
3. **Code:**
   - `models/res_ext.py`
   - `models/page_fm_models.py`
   - `models/page_fm_conversation_models.py`
   - `views/res_partner_views_inherit_pancake.xml`

---

## 👥 CONTRIBUTORS

- **Developer:** GitHub Copilot
- **Date:** 2025-10-29
- **Version:** 1.0

---

## 📞 SUPPORT

Nếu gặp vấn đề, kiểm tra:

1. Log Odoo: `docker logs -f CONTAINER_ID`
2. Field tags đã tồn tại chưa: `partner._fields.get('pancake_tag_ids')`
3. Tags đã sync chưa: `env['page.fm.tag'].search_count([])`

---

**🎉 HOÀN THÀNH! Tags từ Pancake giờ đã tự động đồng bộ về Odoo!**
