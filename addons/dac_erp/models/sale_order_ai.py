from odoo import models
from odoo.exceptions import UserError
import requests
import json
import logging

_logger = logging.getLogger(__name__)


class SaleOrderAI(models.Model):
    _inherit = 'sale.order'

    _AI_DEFAULT_SYSTEM_PROMPT = (
        'Bạn là trợ lý tóm tắt đơn hàng. Phân tích thông tin đơn hàng và tạo tiêu đề ngắn gọn '
        'và mô tả tóm tắt bằng tiếng Việt.\n'
        'Trả về ĐÚNG JSON format: {"title": "...", "summary": "..."}\n'
        'Không thêm bất kỳ text nào ngoài JSON.'
    )
    _AI_DEFAULT_USER_PROMPT = (
        'Tóm tắt đơn hàng:\n'
        'Khách hàng: {partner_name}\n'
        'Số đơn: {order_name}\n'
        'Sản phẩm:\n{order_lines}\n'
        'Tổng tiền: {amount_total}\n'
        'Ghi chú: {note}'
    )

    def _build_ai_summary_prompt(self):
        self.ensure_one()
        lines = []
        for line in self.order_line:
            if line.display_type:
                continue
            lines.append(
                f'- {line.product_id.name or line.name}: {line.product_uom_qty} x {line.price_unit:,.0f}đ'
            )
        icp = self.env['ir.config_parameter'].sudo()
        tmpl = icp.get_param('dac_erp.ai_summary_user_prompt') or self._AI_DEFAULT_USER_PROMPT
        return tmpl.format(
            partner_name=self.partner_id.name or '',
            order_name=self.name or '',
            order_lines='\n'.join(lines) or '(chưa có sản phẩm)',
            amount_total=f'{self.amount_total:,.0f}',
            note=self.note or '',
        )

    def action_ai_summarize(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        endpoint = (icp.get_param('dac_erp.ai_summary_endpoint') or '').rstrip('/')
        api_key = icp.get_param('dac_erp.ai_summary_api_key') or ''
        # Lấy danh sách model hoạt động và ưu tiên từ cơ sở dữ liệu dac_erp.ai_model
        db_models = self.env['dac_erp.ai_model'].sudo().search([('is_active', '=', True)], order='sequence, id')
        model_list = db_models.mapped('name')
        if not model_list:
            # Hỗ trợ cả key cũ (ai_summary_model) lẫn key mới (ai_summary_models) làm fallback
            models_raw = (
                icp.get_param('dac_erp.ai_summary_models')
                or icp.get_param('dac_erp.ai_summary_model')
                or 'gpt-4o-mini'
            )
            model_list = [m.strip() for m in models_raw.split(',') if m.strip()]
        system_prompt = icp.get_param('dac_erp.ai_summary_system_prompt') or self._AI_DEFAULT_SYSTEM_PROMPT

        if not endpoint or not api_key:
            raise UserError('Chưa cấu hình AI Endpoint hoặc API Key trong Cài đặt.')
        if not model_list:
            raise UserError('Chưa cấu hình AI Model trong Cài đặt.')

        user_prompt = self._build_ai_summary_prompt()
        attempt_errors = []

        # Đảm bảo prompt chứa từ "json" — yêu cầu bắt buộc khi dùng response_format: json_object
        json_hint = '\nRespond with a single valid JSON object: {"title": "...", "summary": "..."}'
        combined_prompts = system_prompt + ' ' + user_prompt
        if 'json' not in combined_prompts.lower():
            system_prompt = system_prompt + json_hint

        for model in model_list:
            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.3,
                'response_format': {'type': 'json_object'},
            }
            try:
                resp = requests.post(
                    f'{endpoint}/chat/completions',
                    json=payload,
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    timeout=(10, 60),
                )
                # Nếu bị 400 do response_format, thử lại không dùng response_format
                if resp.status_code == 400:
                    _logger.warning('AI summarize: model %s returned 400 with response_format, retrying without it', model)
                    payload.pop('response_format', None)
                    resp = requests.post(
                        f'{endpoint}/chat/completions',
                        json=payload,
                        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                        timeout=(10, 60),
                    )
                resp.raise_for_status()
                resp.encoding = 'utf-8'
            except requests.exceptions.RequestException as e:
                attempt_errors.append(f'[{model}] lỗi kết nối: {e}')
                _logger.warning('AI summarize: model %s failed for order %s: %s', model, self.name, e)
                continue

            try:
                # Parse HTTP response — endpoint có thể trả về nhiều JSON object nối nhau (NDJSON/streaming)
                try:
                    resp_data = resp.json()
                except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
                    # Fallback: dùng raw_decode để parse JSON object đầu tiên từ response body
                    decoder = json.JSONDecoder()
                    resp_data, _ = decoder.raw_decode(resp.text.strip())

                content = resp_data['choices'][0]['message']['content'].strip()
                _logger.info('AI summarize raw content for order %s (model %s, len=%d): %s',
                             self.name, model, len(content), content[:500])

                # Parse AI content — dùng raw_decode để bỏ qua mọi ký tự thừa phía sau JSON
                decoder = json.JSONDecoder()
                data = None

                first_brace = content.find('{')
                if first_brace != -1:
                    try:
                        data, _ = decoder.raw_decode(content, first_brace)
                    except json.JSONDecodeError:
                        pass

                if data is None:
                    data = json.loads(content)

                self.write({
                    'order_title': (data.get('title') or '')[:255],
                    'order_summary': data.get('summary') or '',
                })
                return  # thành công — dừng fallback
            except (KeyError, IndexError, json.JSONDecodeError, ValueError, requests.exceptions.JSONDecodeError) as e:
                attempt_errors.append(f'[{model}] lỗi parse: {e}')
                _logger.warning('AI summarize: parse failed for model %s, order %s: %s', model, self.name, e)
                continue

        raise UserError('Tất cả model đều thất bại:\n' + '\n'.join(attempt_errors))

    def action_bulk_ai_summarize(self):
        errors = []
        for order in self:
            try:
                order.action_ai_summarize()
            except Exception as e:
                _logger.error('AI summarize failed for order %s: %s', order.name, e)
                errors.append(f'{order.name}: {e}')
        if errors:
            raise UserError('Một số đơn hàng không tóm tắt được:\n' + '\n'.join(errors))
