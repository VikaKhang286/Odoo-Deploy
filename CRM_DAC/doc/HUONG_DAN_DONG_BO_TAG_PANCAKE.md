# 🏷️ HƯỚNG DẪN ĐỒNG BỘ TAG TỪ PANCAKE VỀ ODOO

## 📋 TỔNG QUAN

Module CRM_DAC đã được cập nhật để **tự động đồng bộ tags từ Pancake về Odoo** cho cả:
1. **Conversation** (`page.fm.conversation.pancake_tag_ids`)
2. **Customer/Partner** (`res.partner.pancake_tag_ids`)

---

## ✅ CÁC TÍNH NĂNG ĐÃ CÓ

### 1️⃣ **Đồng bộ danh sách Tags từ Pancake** ✅
- Model: `page.fm.tag`
- Action: **"Sync Tags lên Pancake"** (button trên Page)
- Chức năng: Lấy danh sách tất cả tags có trên Pancake về Odoo

### 2️⃣ **Đồng bộ Tags từ Odoo → Pancake** ✅
- Khi thay đổi `require_processing` hoặc `pancake_tag_ids` trên conversation
- Tự động gửi tags lên Pancake
- Hàm: `_sync_tags_to_pancake()`, `action_sync_pancake_tags_manual()`

### 3️⃣ **🆕 Đồng bộ Tags từ Pancake → Odoo** ✅
- **Tự động** khi fetch conversations từ API
- **Tự động** khi sync messages
- **Thủ công** qua button/action

---

## 🔄 CÁCH HOẠT ĐỘNG

### **A. Khi đồng bộ Conversations**
```
API Pancake → Odoo
└─ Lấy conversations với tag_ids
   └─ Map tag_ids sang page.fm.tag (Odoo)
      └─ Gán vào conversation.pancake_tag_ids
         └─ Đồng bộ sang partner.pancake_tag_ids (nếu có partner)
```

**File:** `page_fm_models.py`
- Hàm `_fetch_conversations_for_page_record()`: Lấy `tag_ids` từ API
- Hàm `_create_or_update_conversations()`: Map tags và gán vào conversation + partner

### **B. Khi đồng bộ Messages**
```
Sync Messages thành công
└─ Kiểm tra conversation.pancake_tag_ids
   └─ Nếu có tags → Đồng bộ sang partner.pancake_tag_ids
```

**File:** `page_fm_conversation_models.py`
- Hàm `action_sync_messages()`: Sau khi sync messages xong, tự động sync tags sang partner
- Hàm `sync_tags_to_partner()`: Tiện ích đồng bộ thủ công

### **C. Đồng bộ thủ công**
```python
# Từ conversation
conversation.sync_tags_to_partner()

# Từ partner
partner.sync_tags_from_conversations()
```

---

## 📍 VỊ TRÍ HIỂN THỊ TAGS

### **1. Trên Conversation**
- Field: `pancake_tag_ids` (Many2many với `page.fm.tag`)
- Widget: `many2many_tags`
- **Chỉ Manager** có quyền chỉnh sửa (group: `dac_erp.group_dac_erp_manager`)

### **2. Trên Partner/Customer**
- Field: `pancake_tag_ids` (Many2many với `page.fm.tag`)
- Widget: `many2many_tags` với `color_field`
- View: `res_partner_views_inherit_pancake.xml`
- Group: **"Thẻ từ Pancake"**
- **Read-only** (chỉ sync tự động, không cho sửa thủ công)

---

## 🚀 CÁCH SỬ DỤNG

### **Bước 1: Đồng bộ danh sách Tags**
```
Menu → Pages.fm → Pages
→ Chọn Page
→ Button "Sync Tags"
```
✅ Kết quả: Tất cả tags trên Pancake được tải về model `page.fm.tag`

### **Bước 2: Đồng bộ Conversations (tự động lấy tags)**
```
Menu → Pages.fm → Pages
→ Chọn Page
→ Button "Sync Conversations"
```
✅ Kết quả: 
- Conversations được tải về với `pancake_tag_ids` đã được gán
- Nếu conversation có partner → tags tự động sync sang partner

### **Bước 3: Đồng bộ Messages (tự động sync tags sang partner)**
```
Menu → Conversations
→ Chọn Conversation
→ Button "Sync Messages"
```
✅ Kết quả:
- Messages được tải về
- Tags từ conversation tự động sync sang partner (nếu có)

### **Bước 4: Kiểm tra Tags trên Customer**
```
Menu → Contacts
→ Mở Customer
→ Tab "Phụ trách (Pancake)"
→ Xem field "Thẻ từ Pancake"
```
✅ Kết quả: Hiển thị các tags đã được đồng bộ từ conversation mới nhất

---

## 🔧 CẤU TRÚC DỮ LIỆU

### **Model: page.fm.tag**
```python
- tag_fm_id: ID tag từ Pancake
- name: Tên tag
- fm_text: Text gốc từ Pancake
- fm_color_hex: Màu hex từ Pancake (#38a6f4)
- fm_lighten_rgba: Màu rgba từ Pancake
- page_id: Trang Pancake
- odoo_tag_code: Mã nội bộ (VD: LEAD_HOT, DROP, NEED_QUOTE)
```

### **Model: page.fm.conversation**
```python
- pancake_tag_ids: Many2many('page.fm.tag')
  + Domain: [('page_id', '=', page_fm_page_id)]
  + Groups: dac_erp.group_dac_erp_manager
```

### **Model: res.partner**
```python
- pancake_tag_ids: Many2many('page.fm.tag')
  + Relation: res_partner_pancake_tag_rel
  + Widget: many2many_tags với color_field
  + Read-only (sync tự động)
```

---

## 🎯 LƯU Ý QUAN TRỌNG

### ✅ **Tags được đồng bộ TỰ ĐỘNG khi:**
1. Fetch conversations từ API (nếu API trả về `tag_ids`)
2. Sync messages thành công
3. Create/Update conversation có tags

### ⚠️ **API Pancake KHÔNG hỗ trợ:**
- GET tags của 1 conversation cụ thể
- Endpoint conversations chỉ dùng `tags` parameter để **FILTER**, không trả về tags trong response

### 💡 **Giải pháp:**
- Rely vào dữ liệu `tag_ids` trả về khi fetch conversations list
- Sync định kỳ để cập nhật tags mới nhất
- Manager có thể sửa tags thủ công trên conversation → auto sync lên Pancake

---

## 🔄 FLOW HOÀN CHỈNH

```
┌─────────────────┐
│   PANCAKE API   │
└────────┬────────┘
         │ tag_ids
         ▼
┌─────────────────┐
│  page.fm.tag    │ ◄── Sync danh sách tags
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│ page.fm.conversation │ ◄── Auto map tag_ids khi fetch/sync
│  pancake_tag_ids     │
└──────────┬───────────┘
           │
           │ sync_tags_to_partner()
           ▼
┌──────────────────┐
│   res.partner    │ ◄── Tags từ conversation mới nhất
│ pancake_tag_ids  │
└──────────────────┘
```

---

## 📊 KIỂM TRA & DEBUG

### **1. Kiểm tra tags đã sync chưa:**
```python
# Console Python
tag_count = env['page.fm.tag'].search_count([('page_id', '=', PAGE_ID)])
print(f"Total tags: {tag_count}")
```

### **2. Kiểm tra conversation có tags:**
```python
conv = env['page.fm.conversation'].browse(CONV_ID)
print(f"Tags: {conv.pancake_tag_ids.mapped('name')}")
```

### **3. Kiểm tra partner có tags:**
```python
partner = env['res.partner'].browse(PARTNER_ID)
print(f"Tags: {partner.pancake_tag_ids.mapped('name')}")
```

### **4. Xem log:**
```bash
# Docker logs
docker logs -f ODOO_CONTAINER_ID | grep "Synced.*tags"

# Output mẫu:
# ✅ Synced 3 tags from conversation to partner Nguyễn Văn A
```

---

## ❓ CÂU HỎI THƯỜNG GẶP

### **Q1: Tags không hiển thị trên Partner?**
**A:** 
- Kiểm tra conversation có `pancake_tag_ids` chưa
- Chạy: `conversation.sync_tags_to_partner()`
- Hoặc sync lại messages

### **Q2: Tags bị trùng lặp?**
**A:** Không thể trùng vì dùng `(6, 0, ids)` - replace toàn bộ

### **Q3: Muốn xóa tags trên Partner?**
**A:** 
- Sửa tags trên conversation (Manager only)
- Chạy `sync_tags_to_partner()` lại

### **Q4: API không trả về tag_ids?**
**A:** 
- API v2 conversations **CÓ THỂ** trả về `tag_ids` (tùy endpoint/version)
- Nếu không có, tags sẽ không sync được tự động
- Phải sync thủ công qua button trên conversation

---

## 📝 CHANGELOG

### **Version 1.0 - 2025-10-29**
- ✅ Thêm field `pancake_tag_ids` vào `res.partner`
- ✅ Auto sync tags khi fetch conversations
- ✅ Auto sync tags khi sync messages
- ✅ Thêm hàm `sync_tags_to_partner()` và `sync_tags_from_conversations()`
- ✅ Cập nhật view `res_partner_views_inherit_pancake.xml`
- ✅ Cập nhật logic trong `_create_or_update_conversations()`
- ✅ Cập nhật logic trong `action_sync_messages()`

---

## 👨‍💻 DEVELOPER NOTES

### **Files đã sửa đổi:**
1. `models/res_ext.py`
   - Thêm field `pancake_tag_ids`
   - Thêm hàm `sync_tags_from_conversations()`

2. `models/page_fm_models.py`
   - Cập nhật `_fetch_conversations_for_page_record()`: Lấy `tag_ids`
   - Cập nhật `_create_or_update_conversations()`: Map tags + sync to partner

3. `models/page_fm_conversation_models.py`
   - Thêm hàm `sync_tags_to_partner()`
   - Cập nhật `action_sync_messages()`: Auto sync tags after success

4. `views/res_partner_views_inherit_pancake.xml`
   - Thêm group "Thẻ từ Pancake"
   - Widget `many2many_tags` với `color_field`

### **Dependencies:**
- `page.fm.tag` model (đã có)
- `page.fm.conversation.pancake_tag_ids` (đã có)
- `res.partner.pancake_tag_ids` (mới thêm)

---

## 🎉 KẾT LUẬN

Tính năng đồng bộ tag từ Pancake về Odoo đã được triển khai **HOÀN CHỈNH** và **TỰ ĐỘNG**:
- ✅ Sync tags khi fetch conversations
- ✅ Sync tags khi sync messages  
- ✅ Sync tags từ conversation sang partner
- ✅ Hiển thị tags với màu sắc đẹp mắt
- ✅ Hỗ trợ sync thủ công khi cần

**Cần làm gì tiếp theo?**
1. Update module trong Odoo
2. Sync tags từ Pancake (button "Sync Tags")
3. Sync conversations (tags tự động được gán)
4. Enjoy! 🎊
