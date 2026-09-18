import requests
from odoo import fields, models
from odoo.exceptions import UserError


class GeminiApiKey(models.Model):
    _name = 'gemini.api.key'
    _description = 'Gemini API Key'
    _order = 'sequence, id'

    name = fields.Char(string='Tên gợi nhớ', required=True, default='Gemini Key')
    key = fields.Char(string='API Key', required=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    is_active = fields.Boolean(string='Hoạt động', default=True)

    def action_test_key(self):
        self.ensure_one()
        if not self.key:
            raise UserError("Vui lòng điền API Key trước khi kiểm tra!")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.key}"
        try:
            res = requests.get(url, timeout=(5, 10))
            if res.status_code != 200:
                error_msg = res.json().get('error', {}).get('message', 'Không xác định')
                raise UserError(f"Kết nối thất bại (HTTP {res.status_code}): {error_msg}")
            
            data = res.json()
            models_list = []
            for m in data.get('models', []):
                methods = m.get('supportedGenerationMethods', [])
                if 'generateContent' in methods:
                    name = m.get('name', '').replace('models/', '')
                    display_name = m.get('displayName', name)
                    models_list.append(f"{display_name} ({name})")
            
            if not models_list:
                raise UserError("Không tìm thấy model nào hỗ trợ generateContent.")
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Kết nối thành công!',
                    'message': 'Các model khả dụng:\n' + '\n'.join(models_list[:15]) + ('\n... và các model khác.' if len(models_list) > 15 else ''),
                    'type': 'success',
                    'sticky': True,
                }
            }
        except Exception as e:
            if isinstance(e, UserError):
                raise e
            raise UserError(f"Có lỗi xảy ra khi kết nối tới API Gemini: {str(e)}")


class GeminiModelPriority(models.Model):
    _name = 'gemini.model.priority'
    _description = 'Gemini Model Priority'
    _order = 'sequence, id'

    model_name = fields.Char(string='Model Gemini', required=True, default='gemini-2.5-flash')
    sequence = fields.Integer(string='Độ ưu tiên', default=10)

    def action_test_model(self):
        self.ensure_one()
        if not self.model_name:
            raise UserError("Vui lòng điền tên Model trước khi kiểm tra!")
        
        # Get active API keys
        api_keys = self.env['gemini.api.key'].search([('is_active', '=', True)], order='sequence, id')
        if not api_keys:
            raise UserError("Không tìm thấy Gemini API Key hoạt động nào để kiểm tra model!")
        
        test_key = api_keys[0]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={test_key.key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": "Say ok"}]}]
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=(5, 10))
            if res.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Model Khả dụng!',
                        'message': f"Model '{self.model_name}' kết nối và hoạt động thành công với API Key '{test_key.name}'!",
                        'type': 'success',
                        'sticky': True,
                    }
                }
            else:
                error_msg = res.json().get('error', {}).get('message', 'Không xác định')
                raise UserError(f"Model không khả dụng hoặc lỗi kết nối (HTTP {res.status_code}): {error_msg}")
        except Exception as e:
            if isinstance(e, UserError):
                raise e
            raise UserError(f"Có lỗi xảy ra khi kết nối tới model {self.model_name}: {str(e)}")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    gemini_api_key_ids = fields.Many2many(
        'gemini.api.key',
        string='Gemini API Keys'
    )

    gemini_model_priority_ids = fields.Many2many(
        'gemini.model.priority',
        string='Model Priorities'
    )

    gemini_api_rotation = fields.Boolean(
        string='Xoay vòng API',
        config_parameter='sale_ai_invoice_reader.gemini_api_rotation',
        default=True,
        help='Nếu chọn, hệ thống sẽ sử dụng xoay vòng (round-robin) các API Key khác nhau cho mỗi lần gọi từ trên xuống.'
    )

    gemini_system_prompt = fields.Char(
        string='Gemini System Prompt',
        config_parameter='sale_ai_invoice_reader.gemini_system_prompt',
        default=(
            "Bạn là một chuyên gia bóc tách dữ liệu kế toán tinh thông. Nhiệm vụ của bạn là phân tích hình ảnh/PDF hóa đơn được cung cấp và trích xuất thông tin thành một chuỗi JSON duy nhất.\n\n"
            "YÊU CẦU ĐẦU RA:\n"
            "- Chỉ trả về chuỗi JSON hợp lệ. KHÔNG giải thích, KHÔNG bọc trong dấu nháy khối ```json.\n"
            "- Các trường số lượng, đơn giá, thành tiền phải là số thuần túy (không chứa dấu chấm, dấu phẩy phân tách hàng nghìn).\n"
            "- Trường số điện thoại phải giữ lại số 0 đầu tiên và viết liền (Ví dụ: \"0901234567\")."
        ),
        help='System Instruction context passed to Gemini for accurate extraction.'
    )

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        api_keys = self.env['gemini.api.key'].search([])
        models_priority = self.env['gemini.model.priority'].search([])
        res.update({
            'gemini_api_key_ids': [(6, 0, api_keys.ids)],
            'gemini_model_priority_ids': [(6, 0, models_priority.ids)],
        })
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        # Clean up any orphaned API keys or model priorities that are no longer linked
        all_keys = self.env['gemini.api.key'].search([])
        linked_keys = self.gemini_api_key_ids
        orphans = all_keys - linked_keys
        if orphans:
            orphans.unlink()

        all_models = self.env['gemini.model.priority'].search([])
        linked_models = self.gemini_model_priority_ids
        orphans_m = all_models - linked_models
        if orphans_m:
            orphans_m.unlink()
