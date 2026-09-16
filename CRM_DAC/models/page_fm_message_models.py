import logging
#import html2text # Đảm bảo thư viện này đã được cài đặt (pip install html2text)
from odoo.tools import html2plaintext
import json # Mặc dù không dùng trực tiếp trong hàm này nhưng có thể cần cho attachments_json ở nơi khác
from odoo import models, fields, api, _
from datetime import datetime
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)

class PageFmMessage(models.Model):
    _name = 'page.fm.message'
    _description = 'Page.fm Message'
    _order = 'inserted_at_fm desc, id desc'
    SYNC_ORIGIN_SELECTION = [
        ('continuous', 'Đồng bộ liên tục'),
        ('manual_window', 'Đồng bộ cửa sổ'),
        ('manual_full', 'Đồng bộ toàn bộ'),
        ('manual_single', 'Đồng bộ một hội thoại'),
        ('wizard', 'Đồng bộ từ wizard'),
    ]

    name = fields.Char(string="Short Content",
                    compute="_compute_display_name", 
                    store=False, help="Tóm tắt nội dung hoặc ID tin nhắn")
    type_content = fields.Char(string="Kiểu content",default='text', help="Kiểu nội dung của tin nhắn, ví dụ: text, image, video, audio, file...")
    url_content = fields.Char(string="URL Content", help="Đường dẫn đến nội dung tin nhắn, nếu có")

    message_fm_id = fields.Char(string="Message FM ID", required=True, index=True, copy=False)


    conversation_id = fields.Many2one(
        'page.fm.conversation', 
        string="Conversation", 
        required=True, 
        ondelete='cascade', 
        index=True
    )
    page_fm_page_id_related = fields.Many2one(
        related='conversation_id.page_fm_page_id',
        string="Page (Related)",
        store=True, 
        readonly=True
    )
    
    sender_name_fm = fields.Char(string="Sender Name (from API)")
    staff_name_fm = fields.Char(string="Staff Name (from API)") 
    staff_id_fm = fields.Char(string="Staff ID (from API)") 
    

    staff = fields.Many2one(
        'res.users',
        string="Staff",
        help="Người dùng Odoo đã xử lý tin nhắn này",
        index=True,
        ondelete='set null',
        copy=False
    )
    
    content_html = fields.Html(string="Content", help="Nội dung tin nhắn dạng HTML từ API")
    attachments_json = fields.Text(string="Attachments (JSON)", help="Dữ liệu đính kèm dạng JSON thô từ API")
    
    inserted_at_fm = fields.Datetime(string="Time Sent (FM)", index=True)
    
    previous_time = fields.Datetime(string="Time previous message (FM)")

    raw_json_message = fields.Text(string="Raw JSON Message", help="Toàn bộ JSON của tin nhắn từ API để tham khảo")

    sync_origin = fields.Selection(
        SYNC_ORIGIN_SELECTION,
        string="Nguồn đồng bộ",
        default='manual_single',
        copy=False,
        index=True,
    )
    sync_window_key = fields.Char(string="Nhóm cửa sổ đồng bộ", copy=False)

    _sql_constraints = [
        ('message_fm_id_conversation_uniq', 'unique(message_fm_id, conversation_id)', 'Message FM ID phải là duy nhất cho mỗi hội thoại!')
    ]

    @api.depends('content_html', 'message_fm_id', 'attachments_json' , 'type_content')
    def _compute_display_name(self):
        for record in self:
            record.name = 'NAME'  # Reset name to avoid stale data
            try:
                if record.content_html:
                    # h = html2text.HTML2Text()
                    # h.ignore_links = True
                    # h.ignore_images = True
                    # plain_text = h.handle(record.content_html or "").strip()
                    
                    plain_text = html2plaintext(record.content_html or "").strip()
                    # (tuỳ chọn) gom dòng cho gọn
                    plain_text = " ".join(plain_text.split())
                    
                    record.name = (plain_text[:75] + '...') if len(plain_text) > 75 else plain_text
                elif record.type_content != 'text'  or (record.attachments_json and record.attachments_json != '[]'):
                    record.name = record.type_content
                else:
                    record.name = f"Msg: {record.message_fm_id or record.id or 'N/A'}"
            
            
            except Exception as e:
                _logger.warning(f"Lỗi khi tính display_name cho message {record.id}: {e}")
                record.name = f"Msg: {record.message_fm_id or record.id or 'N/A'}"



    def action_view_raw_json(self):
        self.ensure_one()
        # Giả sử tên module của bạn là CRM_DAC
        # Nếu tên module khác, hãy thay đổi 'CRM_DAC.view_page_fm_message_raw_json_form' cho phù hợp
        view_id = False
        try:
            view_id = self.env.ref('CRM_DAC.view_page_fm_message_raw_json_form').id
        except ValueError as e: # External ID not found
             _logger.error(f"Không tìm thấy XML ID 'CRM_DAC.view_page_fm_message_raw_json_form': {e}")
             # Có thể fallback mở một form view mặc định hoặc báo lỗi
             # For now, let it raise error or return an empty view list if not found
             pass


        return {
            'type': 'ir.actions.act_window',
            'name': _('Raw Message JSON'),
            'res_model': 'page.fm.message',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'views': [(view_id, 'form')] if view_id else [], 
        }


    @api.model
    def create(self, vals):
        # GỠ BỎ: Không còn gán staff từ message sync nữa
        # Staff sẽ được gán từ conversation API (chính xác hơn)
        
        rec = super().create(vals)
        try:
            conv = rec.conversation_id
            if conv:
                # so sánh bằng inserted_at_fm
                newer = False
                if rec.inserted_at_fm and conv.last_message_sync_fm:
                    newer = rec.inserted_at_fm > conv.last_message_sync_fm
                elif rec.inserted_at_fm and not conv.last_message_sync_fm:
                    newer = True

                if newer:
                    snippet = rec.name or (getattr(rec, 'type_content', None) or 'message')
                    conv.write({
                        'last_message_snippet': snippet,
                        'last_message_sync_fm': rec.inserted_at_fm,
                    })
        except Exception:
            _logger.exception("Failed to update conversation after message create")
        return rec
