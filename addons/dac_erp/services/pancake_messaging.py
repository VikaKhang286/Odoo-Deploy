# -*- coding: utf-8 -*-
"""Pancake/Page.fm outbound messaging service.

Gửi tin nhắn ra Zalo / Facebook / Instagram thông qua Pancake API.

API endpoint (Page.fm public API v1):
    POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conversation_id}/messages
        ?page_access_token={token}
    Body: { "message": "text", "attachments": [...] }

Cấu hình ICP:
- page_fm.access_token : main access token để generate page-specific tokens

Service trả về dict { ok, message_id?, error_code?, error_message?, raw_response? }
"""
import json
import logging

import requests


_logger = logging.getLogger(__name__)


PAGES_FM_MESSAGES_API_BASE = 'https://pages.fm/api/public_api/v1'
SEND_MESSAGE_TIMEOUT = (10, 30)  # connect, read


def send_pancake_message(env, conversation, text, attachment_urls=None):
    """Gửi 1 tin nhắn outbound qua Pancake API.

    Args:
        env: Odoo env
        conversation: page.fm.conversation record (single)
        text: string nội dung
        attachment_urls: list[str] URLs ảnh/file (optional)

    Returns dict:
        {
          'ok': True/False,
          'message_id': str or None,
          'http_status': int or None,
          'error_code': str or None,
          'error_message': str or None,
          'raw_response': str (truncated 4KB),
        }
    """
    if not conversation or not conversation.id:
        return {
            'ok': False,
            'error_code': 'invalid_conversation',
            'error_message': 'Conversation not provided',
        }

    if not text or not isinstance(text, str) or not text.strip():
        return {
            'ok': False,
            'error_code': 'invalid_text',
            'error_message': 'Message text is required',
        }

    # Lấy main access token + generate page token
    icp = env['ir.config_parameter'].sudo()
    main_token = (icp.get_param('page_fm.access_token') or '').strip()
    if not main_token:
        return {
            'ok': False,
            'error_code': 'token_not_configured',
            'error_message': 'page_fm.access_token chưa được set trong ICP',
        }

    page = conversation.page_fm_page_id
    if not page:
        return {
            'ok': False,
            'error_code': 'no_page',
            'error_message': 'Conversation không gắn với page',
        }

    try:
        page_token = page.sudo()._generate_page_specific_access_token(main_token)
    except Exception as exc:
        _logger.exception("Failed to generate page token")
        return {
            'ok': False,
            'error_code': 'token_generation_failed',
            'error_message': str(exc),
        }
    if not page_token:
        return {
            'ok': False,
            'error_code': 'token_generation_failed',
            'error_message': 'Không thể tạo page-specific token',
        }

    page_external_id = conversation.conv_page_fm_id or page.page_fm_id_str
    conversation_fm_id = conversation.conversation_fm_id
    if not page_external_id or not conversation_fm_id:
        return {
            'ok': False,
            'error_code': 'missing_external_ids',
            'error_message': 'page_fm_id_str hoặc conversation_fm_id thiếu',
        }

    url = (f"{PAGES_FM_MESSAGES_API_BASE}/pages/{page_external_id}"
           f"/conversations/{conversation_fm_id}/messages")
    params = {'page_access_token': page_token}
    body = {'message': text.strip()}
    if attachment_urls:
        if not isinstance(attachment_urls, list):
            return {
                'ok': False,
                'error_code': 'invalid_attachments',
                'error_message': 'attachment_urls must be a list',
            }
        body['attachments'] = [{'url': u} for u in attachment_urls if u]

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    try:
        response = requests.post(
            url,
            params=params,
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers=headers,
            timeout=SEND_MESSAGE_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        _logger.warning("Pancake send_message network error: %s", exc)
        return {
            'ok': False,
            'error_code': 'network_error',
            'error_message': str(exc),
        }

    raw = (response.text or '')[:4000]
    if not (200 <= response.status_code < 300):
        return {
            'ok': False,
            'http_status': response.status_code,
            'error_code': 'pancake_api_error',
            'error_message': "HTTP %s" % response.status_code,
            'raw_response': raw,
        }

    # Parse response để lấy message_id (nếu Pancake trả về)
    message_id = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            # API có thể trả về { "id": "...", "message": {...} } hoặc khác
            message_id = (parsed.get('id') or
                          (parsed.get('message') or {}).get('id') or
                          (parsed.get('data') or {}).get('id'))
    except (ValueError, json.JSONDecodeError):
        pass

    return {
        'ok': True,
        'http_status': response.status_code,
        'message_id': message_id,
        'raw_response': raw,
    }
