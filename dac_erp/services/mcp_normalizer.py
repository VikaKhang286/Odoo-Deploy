# -*- coding: utf-8 -*-
import re

from odoo.tools import html2plaintext


_UPPER_SNAKE_RE = re.compile(r'[^A-Z0-9]+')


def _coalesce(*values):
    for value in values:
        if value not in (None, ''):
            return value
    return None


def _coalesce_text(*values):
    for value in values:
        if value in (None, False, ''):
            continue
        value = _clean_string(value)
        if value:
            return value
    return None


def _clean_string(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _compact_whitespace(value):
    cleaned = _clean_string(value)
    if not cleaned:
        return None
    return " ".join(cleaned.split())


def _to_upper_snake(value):
    text = _compact_whitespace(value)
    if not text:
        return None
    normalized = _UPPER_SNAKE_RE.sub('_', text.upper()).strip('_')
    return normalized or None


def _html_to_text(content_html, url_content=None):
    if not content_html:
        return None if url_content else None
    text = html2plaintext(content_html or "")
    text = text.replace('*', '').replace('_', '')
    text = _compact_whitespace(text)
    if not text and url_content:
        return None
    return text


def _infer_attachment_type(source):
    candidate = _compact_whitespace(
        _coalesce(
            source.get('type'),
            source.get('attachment_type'),
            source.get('kind'),
            source.get('media_type'),
            source.get('content_type'),
        )
    )
    if candidate:
        return candidate.lower()

    mime_value = _compact_whitespace(_coalesce(source.get('mime_type'), source.get('mime'), source.get('file_type')))
    if not mime_value:
        return 'unknown'
    lowered = mime_value.lower()
    if 'image' in lowered:
        return 'image'
    if 'video' in lowered:
        return 'video'
    if 'audio' in lowered:
        return 'audio'
    if 'pdf' in lowered or 'doc' in lowered or 'sheet' in lowered or 'presentation' in lowered:
        return 'document'
    return 'unknown'


def _looks_like_attachment_dict(value):
    if not isinstance(value, dict) or not value:
        return False
    if any(key in value for key in (
        'url', 'origin_url', 'original_url', 'download_url', 'thumb_url', 'thumbnail_url',
        'preview_url', 'file_url', 'src', 'filename', 'file_name', 'name', 'mime_type', 'mime',
    )):
        return True
    candidate_type = value.get('type')
    if isinstance(candidate_type, str) and candidate_type.strip().lower() in (
        'image', 'video', 'audio', 'file', 'document', 'attachment', 'photo', 'pdf',
    ):
        return True
    return False


def _map_attachment_item(source):
    if not isinstance(source, dict):
        return None
    item = {
        'type': _infer_attachment_type(source),
        'name': _compact_whitespace(_coalesce(source.get('name'), source.get('file_name'), source.get('filename'), source.get('title'))),
        'mime_type': _compact_whitespace(_coalesce(source.get('mime_type'), source.get('mime'), source.get('file_type'), source.get('format'))),
        'url': _compact_whitespace(_coalesce(source.get('url'), source.get('download_url'), source.get('file_url'), source.get('src'), source.get('href'))),
        'origin_url': _compact_whitespace(_coalesce(source.get('origin_url'), source.get('original_url'), source.get('source_url'), source.get('url'), source.get('download_url'))),
        'description': _compact_whitespace(_coalesce(source.get('description'), source.get('caption'), source.get('text'))),
        'thumb_url': _compact_whitespace(_coalesce(source.get('thumb_url'), source.get('thumbnail_url'), source.get('thumb'), source.get('preview_url'))),
    }
    if not any(item.get(key) for key in ('name', 'mime_type', 'url', 'origin_url', 'thumb_url', 'description')):
        return None
    # Discard placeholder attachments that carry only a name but no URL or mime type.
    # These arise from Pancake special message types (e.g. pzl_chat_recommended) where
    # the name is a person's name, not a filename — no actual media content is present.
    has_media = item.get('url') or item.get('origin_url') or item.get('thumb_url') or item.get('mime_type')
    if not has_media:
        return None
    if not item['type']:
        item['type'] = 'unknown'
    return item


def _flatten_attachment_candidates(value, sink):
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _flatten_attachment_candidates(item, sink)
        return
    if isinstance(value, dict):
        mapped = _map_attachment_item(value) if _looks_like_attachment_dict(value) else None
        if mapped:
            sink.append(mapped)
        for child in value.values():
            if isinstance(child, (list, dict)):
                _flatten_attachment_candidates(child, sink)


def normalize_attachments(raw_attachments):
    if raw_attachments in (None, False, ''):
        return []
    flattened = []
    _flatten_attachment_candidates(raw_attachments, flattened)
    unique = []
    seen = set()
    for item in flattened:
        signature = (
            item.get('type'),
            item.get('name'),
            item.get('mime_type'),
            item.get('url'),
            item.get('origin_url'),
            item.get('thumb_url'),
            item.get('description'),
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(item)
    return unique


def normalize_conversation_item(raw_item, conversation=None):
    raw_item = raw_item or {}
    status = raw_item.get('status') or {}
    customer = raw_item.get('customer') or {}
    page = raw_item.get('page') or {}
    tags = []
    tag_records = (getattr(conversation, 'pancake_tag_ids', None) or getattr(conversation, 'tag_ids', None) or [])
    if tag_records:
        tags = [{
            'id': tag.id,
            'code': _coalesce(getattr(tag, 'odoo_tag_code', None), _to_upper_snake(getattr(tag, 'name', None))),
            'name': getattr(tag, 'name', None),
            'fm_id': getattr(tag, 'tag_fm_id', None),
            'color': getattr(tag, 'fm_color_hex', None),
        } for tag in tag_records]
    else:
        for tag in raw_item.get('tags') or []:
            tags.append({
                'id': tag.get('id'),
                'code': _coalesce(tag.get('code'), _to_upper_snake(tag.get('name'))),
                'name': tag.get('name'),
                'fm_id': tag.get('fm_id'),
                'color': tag.get('color'),
            })

    owner = raw_item.get('owner')
    participants = []
    for participant in raw_item.get('participants') or []:
        participants.append({
            'id': participant.get('id'),
            'name': participant.get('name'),
        })

    return {
        'id': raw_item.get('id') or getattr(conversation, 'id', None),
        'conversation_fm_id': _coalesce_text(raw_item.get('conversation_fm_id'), getattr(conversation, 'conversation_fm_id', None)),
        'customer_name': _coalesce_text(
            raw_item.get('customer_name_clean'),
            raw_item.get('customer_name_fm'),
            raw_item.get('name'),
            getattr(conversation, 'customer_name_clean', None),
            getattr(conversation, 'customer_name_fm', None),
            getattr(conversation, 'name', None),
        ),
        'customer_phone': _coalesce_text(
            customer.get('phone'),
            raw_item.get('phone'),
            getattr(getattr(conversation, 'partner_id', None), 'phone', None),
            getattr(getattr(conversation, 'partner_id', None), 'mobile', None),
            getattr(conversation, 'phone', None),
        ),
        'platform': _coalesce_text(raw_item.get('platform'), getattr(conversation, 'platform_fm', None)),
        'page': {
            'id': page.get('id'),
            'name': page.get('name'),
            'page_fm_id': page.get('page_fm_id'),
        } if page else {
            'id': getattr(getattr(conversation, 'page_fm_page_id', None), 'id', None),
            'name': getattr(getattr(conversation, 'page_fm_page_id', None), 'name', None),
            'page_fm_id': getattr(getattr(conversation, 'page_fm_page_id', None), 'page_fm_id_str', None),
        },
        'owner': {
            'id': owner.get('id'),
            'name': owner.get('name'),
        } if owner else ({
            'id': getattr(getattr(conversation, 'owner_id', None), 'id', None),
            'name': getattr(getattr(conversation, 'owner_id', None), 'name', None),
        } if getattr(conversation, 'owner_id', None) else None),
        'participants': participants,
        'assignee_user_ids': list(raw_item.get('assignee_user_ids') or []),
        'status_state': _coalesce_text(status.get('state'), getattr(conversation, 'status_state', None)),
        'status_label': _coalesce_text(status.get('label'), getattr(conversation, 'status_label', None)),
        'require_processing': bool(_coalesce(status.get('require_processing'), getattr(conversation, 'require_processing', False))),
        'is_unread': bool(_coalesce(status.get('is_unread'), getattr(conversation, 'is_unread_fm', False))),
        'is_unreplied': bool(raw_item.get('is_unreplied')),
        'is_internal_conversation': bool(_coalesce(raw_item.get('is_internal_conversation'), getattr(conversation, 'is_internal_conversation', False))),
        'last_message_at': _coalesce_text(raw_item.get('last_message_at_fm'), getattr(conversation, 'last_message_at_fm', None)),
        'last_customer_message_at': _coalesce_text(raw_item.get('last_customer_message_at'), getattr(conversation, 'last_customer_message_at', None)),
        'last_staff_reply_at': _coalesce_text(raw_item.get('last_staff_reply_at'), getattr(conversation, 'last_staff_reply_at', None)),
        'last_message_snippet': _coalesce_text(
            (raw_item.get('last_message') or {}).get('snippet_clean'),
            (raw_item.get('last_message') or {}).get('snippet'),
            getattr(conversation, 'last_message_snippet_clean', None),
            getattr(conversation, 'last_message_snippet', None),
        ),
        'message_count': raw_item.get('message_count') if raw_item.get('message_count') is not None else getattr(conversation, 'message_count', 0),
        'tags': tags,
        'external_url': _coalesce_text(raw_item.get('external_url'), getattr(conversation, 'external_url', None)),
    }


def normalize_message_item(raw_item):
    raw_item = raw_item or {}
    staff_user = raw_item.get('staff_user') or {}
    content_html = raw_item.get('content_html')
    url_content = raw_item.get('url_content')
    return {
        'id': raw_item.get('id'),
        'message_fm_id': raw_item.get('message_fm_id'),
        'inserted_at': raw_item.get('inserted_at_fm'),
        'sender_role': raw_item.get('sender_role'),
        'sender_name': _coalesce_text(raw_item.get('sender_name_fm'), staff_user.get('name'), raw_item.get('staff_name_fm')),
        'staff_name': _coalesce_text(raw_item.get('staff_name_fm')),
        'staff_user': {
            'id': staff_user.get('id'),
            'name': staff_user.get('name'),
        } if staff_user else None,
        'content_text': _html_to_text(content_html, url_content=url_content),
        'content_html': content_html,
        'type_content': raw_item.get('type_content'),
        'url_content': url_content,
        'attachments': normalize_attachments(raw_item.get('attachments')),
        'conversation_id': (raw_item.get('conversation') or {}).get('id'),
    }


def _selection_label(record, field_name, fallback_value=None):
    if not record or field_name not in getattr(record, '_fields', {}):
        return fallback_value
    field = record._fields[field_name]
    selection = field.selection
    if callable(selection):
        selection = selection(record.env)
    value = getattr(record, field_name, None)
    if value in (None, ''):
        return fallback_value
    try:
        return dict(selection).get(value, fallback_value if fallback_value is not None else value)
    except Exception:
        return fallback_value if fallback_value is not None else value


def _as_float(value, default=None):
    if value in (None, ''):
        return default
    try:
        return float(value)
    except Exception:
        return default


def normalize_order_line_item(line):
    if not line:
        return {
            'id': None,
            'product_id': None,
            'product_name': None,
            'description': None,
            'quantity': 0.0,
            'uom': None,
            'price_unit': 0.0,
            'discount': 0.0,
            'price_subtotal': 0.0,
            'price_total': 0.0,
        }
    return {
        'id': getattr(line, 'id', None),
        'product_id': getattr(getattr(line, 'product_id', None), 'id', None),
        'product_name': getattr(getattr(line, 'product_id', None), 'display_name', None) or getattr(getattr(line, 'product_id', None), 'name', None),
        'description': _coalesce_text(getattr(line, 'description', None), getattr(line, 'name', None)),
        'quantity': _as_float(getattr(line, 'product_uom_qty', None), default=0.0),
        'uom': getattr(getattr(line, 'product_uom', None), 'name', None),
        'price_unit': _as_float(getattr(line, 'price_unit', None), default=0.0),
        'discount': _as_float(getattr(line, 'discount', None), default=0.0),
        'price_subtotal': _as_float(getattr(line, 'price_subtotal', None), default=0.0),
        'price_total': _as_float(getattr(line, 'price_total', None), default=0.0),
    }


def _odoo_false_to_none(value):
    """Normalize Odoo False (empty relational/char field) to None for JSON output."""
    if value is False:
        return None
    return value


def normalize_order_item(
    raw_item,
    order=None,
    conversation=None,
    include_lines=False,
    latest_deposit_invoice=None,
    latest_deposit_payment=None,
):
    raw_item = raw_item or {}
    partner = getattr(order, 'partner_id', None)
    currency = getattr(order, 'currency_id', None)
    salesperson = getattr(order, 'user_id', None)

    lines = []
    if include_lines and order:
        lines = [
            normalize_order_line_item(line)
            for line in order.order_line.sorted(lambda rec: (rec.sequence, rec.id))
        ]

    latest_invoice_payload = None
    if latest_deposit_invoice:
        latest_invoice_payload = {
            'id': latest_deposit_invoice.id,
            'name': latest_deposit_invoice.name,
            'amount_total': _as_float(getattr(latest_deposit_invoice, 'amount_total', None), default=0.0),
            'payment_state': getattr(latest_deposit_invoice, 'payment_state', None),
            'invoice_date': _coalesce_text(getattr(latest_deposit_invoice, 'invoice_date', None)),
        }

    latest_payment_payload = None
    if latest_deposit_payment:
        latest_payment_payload = {
            'id': latest_deposit_payment.id,
            'name': latest_deposit_payment.name,
            'amount': _as_float(getattr(latest_deposit_payment, 'amount', None), default=0.0),
            'date': _coalesce_text(getattr(latest_deposit_payment, 'date', None)),
        }

    note_raw = getattr(order, 'note', None) if order else raw_item.get('note')
    note_value = _odoo_false_to_none(note_raw)
    return {
        'id': raw_item.get('id') or getattr(order, 'id', None),
        'name': _coalesce_text(raw_item.get('name'), getattr(order, 'name', None)),
        # Fallback to `name` when order_number is not yet assigned (new/draft orders).
        'order_number': _coalesce_text(
            raw_item.get('order_number'),
            getattr(order, 'order_number', None),
            raw_item.get('name'),
            getattr(order, 'name', None),
        ),
        'client_order_ref': _coalesce_text(raw_item.get('client_order_ref'), getattr(order, 'client_order_ref', None)),
        'state': _coalesce_text(getattr(order, 'state', None), raw_item.get('state')),
        'state_label': _selection_label(order, 'state'),
        'order_state_custom': _coalesce_text(getattr(order, 'order_state_custom', None), raw_item.get('order_state_custom')),
        'order_state_custom_label': _selection_label(order, 'order_state_custom'),
        'date': _coalesce_text(
            raw_item.get('date'),
            getattr(order, 'date', None),
            (str(getattr(order, 'date_order', None).date()) if getattr(order, 'date_order', None) else None),
        ),
        'date_order': _coalesce_text(raw_item.get('date_order'), getattr(order, 'date_order', None)),
        'create_date': _coalesce_text(raw_item.get('create_date'), getattr(order, 'create_date', None)),
        'amount_total': _as_float(getattr(order, 'amount_total', None), default=_as_float(raw_item.get('amount_total'), default=0.0)),
        'amount_untaxed': _as_float(getattr(order, 'amount_untaxed', None), default=_as_float(raw_item.get('amount_untaxed'), default=0.0)),
        'amount_tax': _as_float(getattr(order, 'amount_tax', None), default=_as_float(raw_item.get('amount_tax'), default=0.0)),
        'currency': {
            'id': getattr(currency, 'id', None),
            'name': getattr(currency, 'name', None),
            'symbol': getattr(currency, 'symbol', None),
        } if currency else None,
        'customer': {
            'id': getattr(partner, 'id', None),
            'name': getattr(partner, 'name', None),
            'phone': _coalesce_text(getattr(partner, 'phone', None)),
            'mobile': _coalesce_text(getattr(partner, 'mobile', None)),
        } if partner else None,
        'conversation': {
            'id': getattr(conversation, 'id', None),
            'conversation_fm_id': getattr(conversation, 'conversation_fm_id', None),
            'customer_name': _coalesce_text(
                getattr(conversation, 'customer_name_clean', None),
                getattr(conversation, 'customer_name_fm', None),
                getattr(conversation, 'name', None),
            ),
        } if conversation else raw_item.get('conversation'),
        'user': {
            'id': getattr(salesperson, 'id', None),
            'name': getattr(salesperson, 'name', None),
        } if salesperson else None,
        'delivery_address': _coalesce_text(getattr(order, 'delivery_address', None), raw_item.get('delivery_address')),
        'installation_address': _coalesce_text(getattr(order, 'installation_address', None), raw_item.get('installation_address')),
        'production_deadline': _coalesce_text(raw_item.get('production_deadline'), getattr(order, 'production_deadline', None)),
        'note': None if note_value is None else str(note_value).strip() or None,
        'has_deposit': bool(getattr(order, 'has_deposit', _coalesce(raw_item.get('flags', {}).get('has_deposit'), raw_item.get('has_deposit'), False))),
        'deposit_amount': _as_float(getattr(order, 'deposit_amount', None), default=_as_float(raw_item.get('deposit', {}).get('amount'), default=0.0)),
        'deposit_invoice_count': int(raw_item.get('deposit_invoice_count') or 0),
        'deposit_payment_count': int(raw_item.get('deposit_payment_count') or 0),
        'latest_deposit_invoice': latest_invoice_payload,
        'latest_deposit_payment': latest_payment_payload,
        'lines': lines if include_lines else [],
        # True when amount_total==0 and no line items — helps clients distinguish
        # empty drafts from orders with legitimately 0-value lines.
        'is_empty_draft': (
            _as_float(getattr(order, 'amount_total', None), default=_as_float(raw_item.get('amount_total'), default=0.0)) == 0.0
            and not lines
            and not (raw_item.get('lines') or [])
            and getattr(order, 'state', raw_item.get('state', '')) in ('draft', 'sent', '')
        ),
    }


def normalize_invoice_item(invoice):
    if not invoice:
        return None
    partner = getattr(invoice, 'partner_id', None)
    currency = getattr(invoice, 'currency_id', None)
    return {
        'id': getattr(invoice, 'id', None),
        'name': _coalesce_text(getattr(invoice, 'name', None), getattr(invoice, 'payment_reference', None)),
        'move_type': _coalesce_text(getattr(invoice, 'move_type', None)),
        'state': _coalesce_text(getattr(invoice, 'state', None)),
        'payment_state': _coalesce_text(getattr(invoice, 'payment_state', None)),
        'invoice_date': _coalesce_text(getattr(invoice, 'invoice_date', None)),
        'amount_total': _as_float(getattr(invoice, 'amount_total', None), default=0.0),
        'amount_residual': _as_float(getattr(invoice, 'amount_residual', None), default=0.0),
        'invoice_origin': _coalesce_text(getattr(invoice, 'invoice_origin', None)),
        'is_deposit_invoice': bool(getattr(invoice, 'dac_deposit_invoice', False)),
        'customer': {
            'id': getattr(partner, 'id', None),
            'name': getattr(partner, 'name', None),
        } if partner else None,
        'currency': {
            'id': getattr(currency, 'id', None),
            'name': getattr(currency, 'name', None),
            'symbol': getattr(currency, 'symbol', None),
        } if currency else None,
    }


def normalize_payment_item(payment):
    if not payment:
        return None
    currency = getattr(payment, 'currency_id', None)
    journal = getattr(payment, 'journal_id', None)
    payment_date = _coalesce_text(getattr(payment, 'date', None), getattr(payment, 'payment_date', None))
    return {
        'id': getattr(payment, 'id', None),
        'name': _coalesce_text(getattr(payment, 'name', None), getattr(payment, 'ref', None)),
        'state': _coalesce_text(getattr(payment, 'state', None)),
        'amount': _as_float(getattr(payment, 'amount', None), default=0.0),
        'currency': {
            'id': getattr(currency, 'id', None),
            'name': getattr(currency, 'name', None),
            'symbol': getattr(currency, 'symbol', None),
        } if currency else None,
        'payment_date': payment_date,
        'journal_id': getattr(journal, 'id', None),
        'journal_name': getattr(journal, 'name', None),
    }


def normalize_order_payment_snapshot(order):
    if not order:
        return None
    currency = getattr(order, 'currency_id', None)
    amount_residual = None
    if 'remaining_amount_display' in order._fields:
        amount_residual = _as_float(getattr(order, 'remaining_amount_display', None), default=0.0)
    if amount_residual is None:
        amount_residual = max(
            _as_float(getattr(order, 'amount_total', None), default=0.0) -
            _as_float(getattr(order, 'deposit_amount', None), default=0.0),
            0.0,
        )
    return {
        'id': getattr(order, 'id', None),
        'name': _coalesce_text(getattr(order, 'name', None)),
        'state': _coalesce_text(getattr(order, 'state', None)),
        'order_state_custom': _coalesce_text(getattr(order, 'order_state_custom', None)),
        'is_deposit_confirmed': bool(getattr(order, 'is_deposit_confirmed', False)),
        'is_payment_confirmed': bool(getattr(order, 'is_payment_confirmed', False)),
        'is_order_completed': bool(getattr(order, 'is_order_completed', False)),
        'amount_total': _as_float(getattr(order, 'amount_total', None), default=0.0),
        'deposit_amount': _as_float(getattr(order, 'deposit_amount', None), default=0.0),
        'amount_residual': amount_residual,
        'currency': {
            'id': getattr(currency, 'id', None),
            'name': getattr(currency, 'name', None),
            'symbol': getattr(currency, 'symbol', None),
        } if currency else None,
    }
