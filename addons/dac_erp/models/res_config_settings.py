import re

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    _MCP_TIME_RE = re.compile(r'^\d{2}:\d{2}$')

    production_default_deadline_days = fields.Integer(
        string='So ngay hoan thanh mac dinh',
        config_parameter='dac_erp.production_default_deadline_days',
        default=3,
        help='So ngay cong them tu ngay hien tai khi dung tuy chon ngay hoan thanh mac dinh truoc luc tien hanh san xuat.',
    )
    mcp_customer_care_sla_minutes_default = fields.Integer(
        string='Customer-care SLA mac dinh (phut)',
        config_parameter='dac_erp.mcp.customer_care.sla_minutes_default',
        default=60,
    )
    mcp_customer_care_urgent_minutes_default = fields.Integer(
        string='Nguong urgent mac dinh (phut)',
        config_parameter='dac_erp.mcp.customer_care.urgent_minutes_default',
        default=120,
    )
    mcp_customer_care_default_policy = fields.Selection(
        selection=[
            ('conservative', 'Conservative'),
            ('standard', 'Standard'),
            ('urgent_only', 'Urgent Only'),
        ],
        string='Policy customer-care mac dinh',
        config_parameter='dac_erp.mcp.customer_care.default_policy',
        default='standard',
    )
    mcp_working_hours_morning_start = fields.Char(
        string='Bat dau buoi sang',
        config_parameter='dac_erp.mcp.working_hours.morning_start',
        default='08:00',
    )
    mcp_working_hours_morning_end = fields.Char(
        string='Ket thuc buoi sang',
        config_parameter='dac_erp.mcp.working_hours.morning_end',
        default='12:00',
    )
    mcp_working_hours_afternoon_start = fields.Char(
        string='Bat dau buoi chieu',
        config_parameter='dac_erp.mcp.working_hours.afternoon_start',
        default='13:30',
    )
    mcp_working_hours_afternoon_end = fields.Char(
        string='Ket thuc buoi chieu',
        config_parameter='dac_erp.mcp.working_hours.afternoon_end',
        default='17:30',
    )
    mcp_working_hours_working_days = fields.Char(
        string='Ngay lam viec',
        config_parameter='dac_erp.mcp.working_hours.working_days',
        default='1,2,3,4,5,6',
        help='1=Thu Hai ... 7=Chu Nhat',
    )
    mcp_working_hours_timezone_mode = fields.Selection(
        selection=[
            ('company', 'Company Timezone'),
            ('user', 'User Timezone'),
            ('fixed', 'Fixed Timezone'),
        ],
        string='Nguon mui gio',
        config_parameter='dac_erp.mcp.working_hours.timezone_mode',
        default='company',
    )
    mcp_working_hours_fixed_timezone = fields.Char(
        string='Fixed timezone',
        config_parameter='dac_erp.mcp.working_hours.fixed_timezone',
        default='Asia/Ho_Chi_Minh',
    )
    mcp_activity_type_todo_xmlid = fields.Char(
        string='XMLID activity To Do',
        config_parameter='dac_erp.mcp.activity_type.todo_xmlid',
        default='mail.mail_activity_data_todo',
    )
    mcp_activity_type_call_xmlid = fields.Char(
        string='XMLID activity Call',
        config_parameter='dac_erp.mcp.activity_type.call_xmlid',
        default='mail.mail_activity_data_call',
    )
    mcp_activity_type_followup_xmlid = fields.Char(
        string='XMLID activity CSKH Follow-up',
        config_parameter='dac_erp.mcp.activity_type.followup_xmlid',
        default='dac_erp.mail_activity_type_cskh_followup',
    )
    mcp_customer_care_urgent_activity_type = fields.Selection(
        selection=[('call', 'Call'), ('followup', 'CSKH Follow-up'), ('todo', 'To Do'), ('none', 'No Activity')],
        string='Mapping urgent',
        config_parameter='dac_erp.mcp.customer_care.urgent_activity_type',
        default='call',
    )
    mcp_customer_care_high_activity_type = fields.Selection(
        selection=[('call', 'Call'), ('followup', 'CSKH Follow-up'), ('todo', 'To Do'), ('none', 'No Activity')],
        string='Mapping high',
        config_parameter='dac_erp.mcp.customer_care.high_activity_type',
        default='followup',
    )
    mcp_customer_care_medium_activity_type = fields.Selection(
        selection=[('call', 'Call'), ('followup', 'CSKH Follow-up'), ('todo', 'To Do'), ('none', 'No Activity')],
        string='Mapping medium',
        config_parameter='dac_erp.mcp.customer_care.medium_activity_type',
        default='todo',
    )
    mcp_customer_care_low_activity_type = fields.Selection(
        selection=[('call', 'Call'), ('followup', 'CSKH Follow-up'), ('todo', 'To Do'), ('none', 'No Activity')],
        string='Mapping low',
        config_parameter='dac_erp.mcp.customer_care.low_activity_type',
        default='none',
    )
    mcp_conversation_default_scope = fields.Selection(
        selection=[('external', 'External'), ('internal', 'Internal'), ('all', 'All')],
        string='Conversation default scope',
        config_parameter='dac_erp.mcp.conversation.default_scope',
        default='external',
    )
    mcp_conversation_allow_internal_read = fields.Boolean(
        string='Cho phep doc conversation noi bo',
        config_parameter='dac_erp.mcp.conversation.allow_internal_read',
        default=True,
    )
    mcp_order_money_change_confirmation_required = fields.Boolean(
        string='Yeu cau xac nhan khi doi du lieu anh huong tien',
        config_parameter='dac_erp.mcp.order.money_change_confirmation_required',
        default=True,
    )
    mcp_order_money_change_fields = fields.Char(
        string='Danh sach field anh huong tien',
        config_parameter='dac_erp.mcp.order.money_change_fields',
        default='product_uom_qty,price_unit,discount,tax_id,deposit_amount,has_deposit,order_lines',
    )
    mcp_customer_care_auto_run_enabled = fields.Boolean(
        string='Bat auto-run customer-care',
        config_parameter='dac_erp.mcp.customer_care.auto_run_enabled',
        default=False,
    )
    mcp_customer_care_auto_run_dry_run_default = fields.Boolean(
        string='Dry-run mac dinh cho auto-run',
        config_parameter='dac_erp.mcp.customer_care.auto_run_dry_run_default',
        default=True,
    )
    mcp_customer_care_auto_run_batch_limit = fields.Integer(
        string='Batch limit mac dinh auto-run',
        config_parameter='dac_erp.mcp.customer_care.auto_run_batch_limit',
        default=50,
    )
    mcp_customer_care_auto_run_execute_followups = fields.Boolean(
        string='Auto-run duoc tao follow-up',
        config_parameter='dac_erp.mcp.customer_care.auto_run_execute_followups',
        default=True,
    )
    mcp_customer_care_auto_run_execute_notes = fields.Boolean(
        string='Auto-run duoc tao note noi bo',
        config_parameter='dac_erp.mcp.customer_care.auto_run_execute_notes',
        default=True,
    )
    mcp_customer_care_auto_run_execute_triage = fields.Boolean(
        string='Auto-run duoc cap nhat triage an toan',
        config_parameter='dac_erp.mcp.customer_care.auto_run_execute_triage',
        default=True,
    )
    mcp_customer_care_auto_run_exclude_internal = fields.Boolean(
        string='Auto-run loai internal conversation',
        config_parameter='dac_erp.mcp.customer_care.auto_run_exclude_internal',
        default=True,
    )
    mcp_customer_care_auto_run_allow_mark_read = fields.Boolean(
        string='Future flag: cho phep mark read',
        config_parameter='dac_erp.mcp.customer_care.auto_run_allow_mark_read',
        default=False,
    )
    mcp_customer_care_auto_run_allow_done = fields.Boolean(
        string='Future flag: cho phep set done',
        config_parameter='dac_erp.mcp.customer_care.auto_run_allow_done',
        default=False,
    )
    mcp_customer_care_auto_run_cron_enabled = fields.Boolean(
        string='Bat cron auto-run',
        config_parameter='dac_erp.mcp.customer_care.auto_run_cron_enabled',
        default=False,
    )
    mcp_customer_care_auto_run_cron_interval_minutes = fields.Integer(
        string='Khoang cach cron auto-run (phut)',
        config_parameter='dac_erp.mcp.customer_care.auto_run_cron_interval_minutes',
        default=30,
    )
    mcp_customer_care_auto_run_working_hours_only = fields.Boolean(
        string='Cron chi chay trong gio lam viec',
        config_parameter='dac_erp.mcp.customer_care.auto_run_working_hours_only',
        default=True,
    )
    mcp_max_batch_limit_default = fields.Integer(
        string='MCP max batch limit',
        config_parameter='dac_erp.mcp.max_batch_limit_default',
        default=100,
    )
    mcp_auto_run_min_interval_seconds = fields.Integer(
        string='Khoang cach toi thieu giua cac auto-run (giay)',
        config_parameter='dac_erp.mcp.auto_run_min_interval_seconds',
        default=60,
    )

    @api.constrains('production_default_deadline_days')
    def _check_production_default_deadline_days(self):
        for rec in self:
            if rec.production_default_deadline_days < 1:
                raise ValidationError('So ngay hoan thanh mac dinh phai lon hon hoac bang 1.')

    @api.constrains(
        'mcp_customer_care_sla_minutes_default',
        'mcp_customer_care_urgent_minutes_default',
        'mcp_customer_care_auto_run_batch_limit',
        'mcp_customer_care_auto_run_cron_interval_minutes',
        'mcp_max_batch_limit_default',
        'mcp_auto_run_min_interval_seconds',
        'mcp_working_hours_morning_start',
        'mcp_working_hours_morning_end',
        'mcp_working_hours_afternoon_start',
        'mcp_working_hours_afternoon_end',
        'mcp_working_hours_working_days',
    )
    def _check_mcp_openclaw_settings(self):
        for rec in self:
            if rec.mcp_customer_care_sla_minutes_default < 0:
                raise ValidationError('Customer-care SLA mac dinh phai lon hon hoac bang 0.')
            if rec.mcp_customer_care_urgent_minutes_default < 0:
                raise ValidationError('Nguong urgent mac dinh phai lon hon hoac bang 0.')
            if rec.mcp_customer_care_auto_run_batch_limit < 1 or rec.mcp_customer_care_auto_run_batch_limit > 100:
                raise ValidationError('Batch limit auto-run phai trong khoang 1..100.')
            if rec.mcp_customer_care_auto_run_cron_interval_minutes < 5 or rec.mcp_customer_care_auto_run_cron_interval_minutes > 1440:
                raise ValidationError('Khoang cach cron auto-run phai trong khoang 5..1440 phut.')
            if rec.mcp_max_batch_limit_default < 1 or rec.mcp_max_batch_limit_default > 100:
                raise ValidationError('MCP max batch limit phai trong khoang 1..100.')
            if rec.mcp_auto_run_min_interval_seconds < 0:
                raise ValidationError('Khoang cach toi thieu giua cac auto-run khong duoc am.')
            morning_start = rec._parse_mcp_time_or_raise(rec.mcp_working_hours_morning_start, 'Bat dau buoi sang')
            morning_end = rec._parse_mcp_time_or_raise(rec.mcp_working_hours_morning_end, 'Ket thuc buoi sang')
            afternoon_start = rec._parse_mcp_time_or_raise(rec.mcp_working_hours_afternoon_start, 'Bat dau buoi chieu')
            afternoon_end = rec._parse_mcp_time_or_raise(rec.mcp_working_hours_afternoon_end, 'Ket thuc buoi chieu')
            if morning_start >= morning_end:
                raise ValidationError('Bat dau buoi sang phai nho hon ket thuc buoi sang.')
            if afternoon_start >= afternoon_end:
                raise ValidationError('Bat dau buoi chieu phai nho hon ket thuc buoi chieu.')
            rec._parse_mcp_working_days_or_raise(rec.mcp_working_hours_working_days)

    def _parse_mcp_time_or_raise(self, value, label):
        value = (value or '').strip()
        if not self._MCP_TIME_RE.match(value):
            raise ValidationError('%s phai theo dinh dang HH:MM.' % label)
        hour, minute = [int(part) for part in value.split(':', 1)]
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValidationError('%s phai la gio hop le.' % label)
        return hour * 60 + minute

    def _parse_mcp_working_days_or_raise(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise ValidationError('Ngay lam viec khong duoc de trong.')
        seen = set()
        for raw_part in cleaned.split(','):
            part = raw_part.strip()
            if not part or not part.isdigit():
                raise ValidationError('Ngay lam viec chi duoc chua cac so tu 1 den 7.')
            day = int(part)
            if day < 1 or day > 7:
                raise ValidationError('Ngay lam viec chi duoc chua cac so tu 1 den 7.')
            seen.add(day)
        if not seen:
            raise ValidationError('Ngay lam viec khong duoc de trong.')

    # ── AI Order Summary (OpenAI-compatible) ──────────────────────────────
    ai_summary_endpoint = fields.Char(
        string='AI Endpoint (OpenAI-compatible)',
        config_parameter='dac_erp.ai_summary_endpoint',
        help='VD: https://api.openai.com/v1 hoặc endpoint tương thích OpenAI',
    )
    ai_summary_api_key = fields.Char(
        string='AI API Key',
        config_parameter='dac_erp.ai_summary_api_key',
    )
    ai_summary_models = fields.Char(
        string='AI Models (fallback)',
        config_parameter='dac_erp.ai_summary_models',
        default='gpt-4o-mini',
        help='Danh sách model theo thứ tự ưu tiên, cách nhau bằng dấu phẩy. '
             'VD: gpt-4o,gpt-4o-mini,gpt-3.5-turbo — nếu model đầu lỗi sẽ thử model tiếp theo.',
    )
    ai_summary_system_prompt = fields.Char(
        string='System Prompt',
        config_parameter='dac_erp.ai_summary_system_prompt',
    )
    ai_summary_user_prompt = fields.Char(
        string='User Prompt Template',
        config_parameter='dac_erp.ai_summary_user_prompt',
        help='Biến: {partner_name}, {order_name}, {order_lines}, {amount_total}, {note}',
    )

    ai_model_ids = fields.Many2many(
        'dac_erp.ai_model',
        relation='res_config_settings_dac_erp_ai_model_all_rel',
        column1='config_id',
        column2='model_id',
        string='Danh sách model khả dụng',
    )
    ai_selected_model_ids = fields.Many2many(
        'dac_erp.ai_model',
        relation='res_config_settings_dac_erp_ai_model_sel_rel',
        column1='config_id',
        column2='model_id',
        string='Danh sách model đã chọn',
    )

    @api.onchange('ai_model_ids')
    def _onchange_ai_model_ids(self):
        selected = self.ai_model_ids.filtered(lambda m: m.is_active)
        self.ai_selected_model_ids = [(6, 0, selected.sorted(key=lambda m: (m.sequence or 10, m._origin.id or 0, m.name or '')).ids)]

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        all_models = self.env['dac_erp.ai_model'].sudo().search([], order='sequence, id')
        selected_models = all_models.filtered(lambda m: m.is_active)
        res.update({
            'ai_model_ids': [(6, 0, all_models.ids)],
            'ai_selected_model_ids': [(6, 0, selected_models.ids)],
        })
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        
        # 1. Update sequences and set is_active = True for selected models
        for seq, model in enumerate(self.ai_selected_model_ids):
            model.sudo().write({
                'is_active': True,
                'sequence': (seq + 1) * 10
            })
            
        # 2. Set is_active = False for models not selected
        inactive_models = self.ai_model_ids - self.ai_selected_model_ids
        inactive_models.sudo().write({'is_active': False})

        # 3. Clean up orphaned models deleted from available models
        all_db_models = self.env['dac_erp.ai_model'].sudo().search([])
        orphans = all_db_models - self.ai_model_ids
        if orphans:
            orphans.unlink()

    def action_fetch_ai_models(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        endpoint = (icp.get_param('dac_erp.ai_summary_endpoint') or '').rstrip('/')
        api_key = icp.get_param('dac_erp.ai_summary_api_key') or ''
        if not endpoint or not api_key:
            raise UserError('Chưa cấu hình AI Endpoint hoặc API Key. Hãy lưu cài đặt trước.')
        try:
            resp = requests.get(
                f'{endpoint}/models',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=(10, 30),
            )
            resp.raise_for_status()
            data = resp.json()
            model_ids = sorted(m.get('id', '') for m in (data.get('data') or []) if m.get('id'))
            if not model_ids:
                raise UserError('Endpoint không trả về danh sách model (định dạng không chuẩn OpenAI).')
                
            # Synchronize models in database
            AiModel = self.env['dac_erp.ai_model']
            existing_models = {m.name: m for m in AiModel.sudo().search([])}
            
            created_count = 0
            for model_id in model_ids:
                if model_id not in existing_models:
                    AiModel.sudo().create({
                        'name': model_id,
                        'is_active': False,
                        'sequence': 10,
                    })
                    created_count += 1
            
            message = f'Tìm thấy {len(model_ids)} model từ API.\n'
            if created_count > 0:
                message += f'Đã thêm {created_count} model mới vào danh sách khả dụng bên dưới.'
            else:
                message += 'Danh sách model khả dụng đã được cập nhật đầy đủ.'
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Đồng bộ model thành công',
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'}
                }
            }
        except requests.exceptions.RequestException as e:
            raise UserError(f'Không thể kết nối endpoint: {e}') from e

