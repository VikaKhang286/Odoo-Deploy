# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessDenied
import os
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

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
        """
        _logger.info("Pancake Webhook: Yêu cầu nhận được.")

        # 1. Xác thực Request từ Pancake (Kiểm tra X-API-KEY)
        # Lấy secret key đã cấu hình trong Odoo (nên lưu trong System Parameters)
        # Ví dụ: request.env['ir.config_parameter'].sudo().get_param('pancake.webhook_secret_key')
        # Trong ví dụ này, chúng ta sẽ tạm hardcode (KHÔNG NÊN LÀM TRONG PRODUCTION)
        # Key này phải khớp với key bạn cấu hình trong Pancake (webhook_headers)
        # expected_api_key = "elqsF9ERiFWGacWQO9Gg5XC4kXojot" # Lấy từ cấu hình Pancake của bạn

        # Lấy giá trị X-API-KEY từ header của request
        # received_api_key = request.httprequest.headers.get('X-API-KEY')

        # if not received_api_key or received_api_key != expected_api_key:
        #     _logger.warning(f"Pancake Webhook: Xác thực thất bại. X-API-KEY không hợp lệ hoặc bị thiếu. Nhận được: {received_api_key}")
        #     # Trả về lỗi 401 Unauthorized
        #     return request.make_response(
        #         json.dumps({'status': 'error', 'message': 'Unauthorized: Invalid or missing X-API-KEY'}),
        #         headers={'Content-Type': 'application/json'},
        #         status=401
        #     )
        _logger.info("Pancake Webhook: Xác thực X-API-KEY thành công.")

        # 2. Lấy và Parse dữ liệu JSON từ Pancake
        try:
            raw_data = request.httprequest.data.decode('utf-8')
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