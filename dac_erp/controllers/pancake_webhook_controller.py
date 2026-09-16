# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


# Phase 1 security: webhook authentication.
# Mode được điều khiển qua ICP `dac_erp.pancake_webhook_auth_mode`:
#   - 'disabled' (mặc định nếu chưa cấu hình)  : behavior cũ — chỉ log warning,
#                                                vẫn xử lý webhook (backward compat)
#   - 'api_key'                                : yêu cầu header X-API-KEY khớp
#                                                ICP `dac_erp.pancake_webhook_secret`
#   - 'hmac'                                   : yêu cầu header X-Pancake-Signature
#                                                là HMAC-SHA256 của raw body với
#                                                key ICP `dac_erp.pancake_webhook_secret`
# Khuyến nghị production: dùng 'hmac'. Khi chuyển mode phải coordinate với Pancake.
PANCAKE_AUTH_MODE_PARAM = 'dac_erp.pancake_webhook_auth_mode'
PANCAKE_WEBHOOK_SECRET_PARAM = 'dac_erp.pancake_webhook_secret'


def _verify_pancake_webhook_auth(raw_body_bytes):
    """Kiểm tra auth webhook Pancake. Trả None nếu OK, hoặc Response error.

    `raw_body_bytes` phải là bytes — dùng cho HMAC. Không decode trước.
    """
    icp = request.env['ir.config_parameter'].sudo()
    mode = (icp.get_param(PANCAKE_AUTH_MODE_PARAM) or 'disabled').strip().lower()
    if mode in ('', 'disabled', 'off', 'none'):
        # Backward compat — log warning, không reject
        _logger.warning("Pancake webhook auth is DISABLED (ICP %s). "
                        "Production cần set mode='hmac' hoặc 'api_key'.",
                        PANCAKE_AUTH_MODE_PARAM)
        return None

    secret = (icp.get_param(PANCAKE_WEBHOOK_SECRET_PARAM) or '').strip()
    if not secret:
        _logger.error("Pancake webhook auth mode=%s nhưng ICP %s chưa set.",
                      mode, PANCAKE_WEBHOOK_SECRET_PARAM)
        return request.make_response(
            json.dumps({'status': 'error', 'message': 'webhook secret not configured'}),
            headers={'Content-Type': 'application/json'},
            status=503,
        )

    if mode == 'api_key':
        provided = request.httprequest.headers.get('X-API-KEY') or ''
        if not provided:
            _logger.warning("Pancake webhook: missing X-API-KEY header")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'missing X-API-KEY'}),
                headers={'Content-Type': 'application/json'},
                status=401,
            )
        if not hmac.compare_digest(str(provided).strip(), secret):
            _logger.warning("Pancake webhook: X-API-KEY mismatch")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'invalid X-API-KEY'}),
                headers={'Content-Type': 'application/json'},
                status=403,
            )
        return None

    if mode == 'hmac':
        provided_sig = (request.httprequest.headers.get('X-Pancake-Signature') or '').strip()
        if not provided_sig:
            _logger.warning("Pancake webhook: missing X-Pancake-Signature header")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'missing X-Pancake-Signature'}),
                headers={'Content-Type': 'application/json'},
                status=401,
            )
        # Cho phép prefix 'sha256=' theo convention phổ biến (GitHub style)
        if provided_sig.startswith('sha256='):
            provided_sig = provided_sig[len('sha256='):]
        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_sig.lower(), expected.lower()):
            _logger.warning("Pancake webhook: HMAC signature mismatch")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'invalid signature'}),
                headers={'Content-Type': 'application/json'},
                status=403,
            )
        return None

    # Unknown mode
    _logger.error("Pancake webhook: unknown auth mode %r in ICP", mode)
    return request.make_response(
        json.dumps({'status': 'error', 'message': 'auth mode misconfigured'}),
        headers={'Content-Type': 'application/json'},
        status=503,
    )


class PancakeWebhookController(http.Controller):

    @http.route('/dac_erp/pancake_webhook', type='http', auth='none', methods=['GET'], csrf=False)
    def get_handle_pancake_webhook(self, **kwargs):
        return request.make_response(
                json.dumps({'status': 'error', 'message': 'Invalid Method GET'}),
                headers={'Content-Type': 'application/json'},
                status=400 # Bad Request
            )

    @http.route('/dac_erp/pancake_webhook', type='http', auth='none', methods=['POST'], csrf=False)
    def handle_pancake_webhook(self, **kwargs):
        """
        Endpoint để nhận dữ liệu webhook từ Pancake.
        URL này sẽ được cấu hình trong Pancake: https://your_odoo_domain.com/dac_erp/pancake_webhook

        Auth được điều khiển qua ICP `dac_erp.pancake_webhook_auth_mode`.
        Production: 'hmac' với HMAC-SHA256(secret, raw_body) trong header X-Pancake-Signature.
        """
        _logger.info("Pancake Webhook: Yêu cầu nhận được.")

        # 1. Đọc raw body TRƯỚC KHI verify (HMAC cần raw bytes)
        try:
            raw_body_bytes = request.httprequest.data or b''
        except Exception as e:
            _logger.error("Pancake Webhook: lỗi đọc raw body: %s", e)
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'cannot read body'}),
                headers={'Content-Type': 'application/json'},
                status=400,
            )

        # 2. Xác thực Request từ Pancake
        auth_error = _verify_pancake_webhook_auth(raw_body_bytes)
        if auth_error is not None:
            return auth_error
        _logger.info("Pancake Webhook: Xác thực thành công.")

        # 3. Lấy và Parse dữ liệu JSON từ Pancake
        try:
            raw_data = raw_body_bytes.decode('utf-8') if raw_body_bytes else ''
            if not raw_data:
                _logger.warning("Pancake Webhook: Không có dữ liệu trong request body.")
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'No data provided in request body'}),
                    headers={'Content-Type': 'application/json'},
                    status=400  # Bad Request
                )

            payload = json.loads(raw_data)
            _logger.info(f"Pancake Webhook: Dữ liệu nhận được: json.dumps(payload, indent=2)")
            _logger.info("=====================================================")
            # _logger.info(
            #     "Pancake Webhook: Dữ liệu nhận được: %s",
            #     json.dumps(payload, ensure_ascii=False, indent=2)
            # )

            

        except json.JSONDecodeError:
            _logger.error("Pancake Webhook: Lỗi khi parse JSON từ request body.")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'Invalid JSON format'}),
                headers={'Content-Type': 'application/json'},
                status=400 # Bad Request
            )
        except Exception as e:
            _logger.error(f"Pancake Webhook: Lỗi không xác định khi xử lý request data: {e}")
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'Error processing request data'}),
                headers={'Content-Type': 'application/json'},
                status=500 # Internal Server Error
            )

        # 3. Xử lý dữ liệu dựa trên loại sự kiện (webhook_types)
        # Pancake có thể gửi một trường để xác định loại sự kiện, ví dụ: "event_type" hoặc "type"
        # Bạn cần kiểm tra tài liệu của Pancake để biết chính xác tên trường này.
        # Giả sử payload có trường 'event_type'
        event_type = payload.get('type') # Hoặc payload.get('type') tùy thuộc vào Pancake
        # self._log_data_to_js_file(f'{event_type}', payload)

        # KHÔNG HARDCODE user nữa - để logic trong model tự xác định
        try:
            if event_type == 'orders': # Hoặc giá trị tương ứng với "orders" từ webhook_types
                self._process_order_event(payload)
                order_data = payload.get('order_details') if 'order_details' in payload else payload
                # Gọi trực tiếp không cần with_user()
                request.env['sale.order'].sudo().action_sync_single_pancake_order(order_data)

            elif event_type == 'customers': # Hoặc giá trị tương ứng với "customers"
                self._process_customer_event(payload)
                # _log_data_to_js_file('process_customer_event', payload)
            elif event_type == 'variations_warehouses': # Hoặc giá trị tương ứng
                self._process_inventory_event(payload)
                # _log_data_to_js_file('process_inventory_event', payload)
            else:
                # self._log_data_to_js_file('process_nottype_event', payload)
                _logger.warning(f"Pancake Webhook: Loại sự kiện không xác định hoặc không được hỗ trợ: {event_type}")
                # Bạn có thể chọn trả về lỗi hoặc thành công nếu không muốn xử lý loại sự kiện này
                # return request.make_response(
                #     json.dumps({'status': 'warning', 'message': f'Unsupported event type: {event_type}'}),
                #     headers={'Content-Type': 'application/json'},
                #     status=202 # Accepted (but not processed) or 400 Bad Request
                # )
        except Exception as e:
            _logger.error(f"Pancake Webhook: Lỗi trong quá trình xử lý sự kiện '{event_type}': {e}")
            # Không nên trả về chi tiết lỗi (e) cho client trong production
            return request.make_response(
                json.dumps({'status': 'error', 'message': f'Error processing event {event_type}'}),
                headers={'Content-Type': 'application/json'},
                status=500
            )

        # 4. Trả về phản hồi thành công cho Pancake
        _logger.info(f"Pancake Webhook: Sự kiện '{event_type}' đã được xử lý (hoặc ghi nhận).")
        #### gọi hàm trong 1 model cùng modules
        # request.env['sale.order'].sudo().action_sync_pancake_all_orders()

        # company = request.env.company or request.env.user.company_id
        # orders = request.env['sale.order'].with_context(company_id=company.id).sudo()
        # orders.action_sync_pancake_all_orders()


        
        return request.make_response(
            json.dumps({'status': 'success', 'message': 'Webhook received and acknowledged'}),
            headers={'Content-Type': 'application/json'},
            status=200 # OK
        )

    def _process_order_event(self, data):
        _logger.info(f"Pancake Webhook: Đang xử lý sự kiện đơn hàng: {data.get('id', 'N/A')}")
        # TODO: Logic xử lý đơn hàng
        # Ví dụ:
        # order_data = data.get('order_details') # Tên trường thực tế có thể khác
        # if order_data:
        #     # request.env['sale.order'].sudo().create({...})
        #     pass
        pass

    def _process_customer_event(self, data):
        _logger.info(f"Pancake Webhook: Đang xử lý sự kiện khách hàng: {data.get('id', 'N/A')}")
        
        # TODO: Thêm logic để tạo/cập nhật res.partner (Khách hàng) trong Odoo
        # Ví dụ:
        # customer_data = data.get('customer_info') # Tên trường thực tế có thể khác
        # if customer_data:
        #     # request.env['res.partner'].sudo().create({...})
        #     pass
        pass

    def _process_inventory_event(self, data):
        _logger.info(f"Pancake Webhook: Đang xử lý sự kiện kho/biến thể: {data.get('id', 'N/A')}")
        # TODO: Thêm logic để cập nhật tồn kho (stock.quant, product.product) trong Odoo
        pass

    def _log_data_to_js_file(self, func_name, data):
        # Đường dẫn thư mục ngoài host (mount từ Docker volume)
        output_dir = '/tmp'
        os.makedirs(output_dir, exist_ok=True)

        # Tạo tên file dạng: 20250607_142533__function_name.js
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f"{timestamp}__{func_name}.js"
        file_path = os.path.join(output_dir, file_name)

        # Ghi dữ liệu JSON ra file JS (dạng export const ...)
        with open(file_path, 'w', encoding='utf-8') as f:
            js_var_name = f"data_{func_name}"
            json_content = json.dumps(data, indent=4, ensure_ascii=False)
            f.write(f"export const {js_var_name} = {json_content};\n")

        _logger.info(f"Đã ghi log Pancake ra file: {file_path}")