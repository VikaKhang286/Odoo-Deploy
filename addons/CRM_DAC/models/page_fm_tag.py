# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ==== Base URLs (tận dụng hằng số đã có trong module) ====
try:
    from .page_fm_models import (
        PAGES_FM_PUBLIC_API_V2_BASE_URL,
        PAGES_FM_PUBLIC_API_V1_BASE_URL,
    )
except Exception:
    PAGES_FM_PUBLIC_API_V2_BASE_URL = "https://pages.fm/api/public_api/v2"
    PAGES_FM_PUBLIC_API_V1_BASE_URL = "https://pages.fm/api/public_api/v1"


class PageFmTag(models.Model):
    """
    Cấu trúc tag riêng cho Pancake (KHÔNG mapping crm.tag).
    """
    _name = "page.fm.tag"
    _description = "Pancake Tag"
    _order = "page_id, name"

    # ----- Dữ liệu từ Pancake -----
    name = fields.Char("Tên tag (Pancake)", required=True, index=True)  # alias của fm_text để hiển thị
    tag_fm_id = fields.Char("Tag ID (Pancake)", required=True, index=True)
    page_id = fields.Many2one("page.fm.page", "Trang Pancake", required=True, ondelete="cascade", index=True)

    fm_text = fields.Char("Text (Pancake)")
    fm_color_hex = fields.Char("Màu (hex) từ Pancake")            # ví dụ: #38a6f4
    fm_lighten_rgba = fields.Char("Màu nhạt (rgba) từ Pancake")    # ví dụ: rgba(56,166,244,0.4)
    fm_is_lead_event = fields.Boolean("is_lead_event (Pancake)")

    # ----- Tag nội bộ Odoo (tự định nghĩa) -----
    odoo_tag_code = fields.Char("Mã tag nội bộ", help="VD: LEAD_HOT, DROP, NEED_QUOTE…")
    odoo_tag_label = fields.Char("Nhãn/ghi chú nội bộ")

    active = fields.Boolean(default=True)
    color = fields.Integer("Màu")  # palette Odoo (tùy chọn)

    # ----- AI management flag -----
    managed_by_ai = fields.Boolean(
        'AI có thể quản lý',
        default=False,
        help=(
            "True = AI/OpenClaw có thể thêm/gỡ tag này khi dùng mode replace_ai_scope. "
            "False = chỉ thao tác thủ công; AI không được touch trong replace_ai_scope."
        ),
    )

    # Preview màu đúng như Pancake
    badge_preview = fields.Html("Preview", compute="_compute_badge_preview", sanitize=False, readonly=True)

    _sql_constraints = [
        ("uniq_tag_per_page", "unique(tag_fm_id, page_id)", "Tag (Pancake) phải là duy nhất trong một Page!"),
        ("uniq_internal_code_per_page", "unique(odoo_tag_code, page_id)", "Mã tag nội bộ đã tồn tại trên trang này!"),
    ]

    # ========================== UI helper ==========================
    def _compute_badge_preview(self):
        def _yiq(hexcolor):
            try:
                hexcolor = hexcolor.lstrip('#')
                r, g, b = int(hexcolor[0:2], 16), int(hexcolor[2:4], 16), int(hexcolor[4:6], 16)
                return 'black' if (r*299 + g*587 + b*114)/1000 > 150 else 'white'
            except Exception:
                return 'white'

        for rec in self:
            label = rec.fm_text or rec.name or rec.tag_fm_id or ""
            bg = (rec.fm_color_hex or "").strip()
            if bg.startswith('#') and len(bg) in (4, 7):
                fg = _yiq(bg)
                rec.badge_preview = (
                    f'<span class="badge" style="background-color:{bg};color:{fg};'
                    f'padding:4px 8px;border-radius:10px;">{label}</span>'
                )
            else:
                rec.badge_preview = f'<span class="badge">{label}</span>'

    # ========================== Tokens ==========================
    @api.model
    def _get_main_token(self):
        """API key chính (bearer) chỉ dùng để xin page_access_token."""
        return self.env["ir.config_parameter"].sudo().get_param("page_fm.access_token")

    def _get_page_token(self, page):
        """Xin page_access_token từ model Page (đã có sẵn trong hệ thống)."""
        main_token = self._get_main_token()
        if not main_token:
            raise UserError(_("Thiếu 'page_fm.access_token' trong Thông số hệ thống"))
        return page._generate_page_specific_access_token(main_token)

    # ========================== Fetch tags ==========================
    def _parse_items_to_rows(self, items):
        """Chuẩn hoá mảng item (dict hoặc string) -> list rows có id/text/color/..."""
        out = []
        if isinstance(items, dict):
            items = items.get("items") or items.get("rows") or []
        for it in (items or []):
            if isinstance(it, dict):
                tid = it.get("id") or it.get("tag_id")
                txt = it.get("text") or it.get("name") or tid
                row = {
                    "id": str(tid) if tid is not None else "",
                    "text": str(txt) if txt is not None else str(tid),
                    "color": it.get("color"),
                    "lighten_color": it.get("lighten_color"),
                    "is_lead_event": bool(it.get("is_lead_event")),
                }
                if row["id"]:
                    out.append(row)
            else:
                tid = str(it).strip()
                if tid:
                    out.append({"id": tid, "text": tid})
        return out

    def _fetch_page_tags_v1(self, page, page_token):
        """List tags (v1) — theo đúng docs bạn cung cấp."""
        url = f"{PAGES_FM_PUBLIC_API_V1_BASE_URL}/pages/{page.page_fm_id_str}/tags"
        params = {"page_access_token": page_token, "page_id": page.page_fm_id_str}
        headers = {"Accept": "application/json", "User-Agent": "odoo/18 CRM_DAC"}
        _logger.info("Fetching v1 tags: %s params={'page_id': '%s'}", url, page.page_fm_id_str)
        resp = requests.get(url, params=params, headers=headers, timeout=25)
        if not resp.ok:
            _logger.warning("Tags v1 HTTP %s: %s", resp.status_code, resp.text[:200])
            return []
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            _logger.warning("Tags v1 non-JSON: %s", resp.text[:200])
            return []
        items = data.get("tags") or data.get("data") or data or []
        return self._parse_items_to_rows(items)

    def _fetch_page_tags_v2(self, page, page_token):
        """Thử v2 nếu cần (một số page có thể ok)."""
        url = f"{PAGES_FM_PUBLIC_API_V2_BASE_URL}/pages/{page.page_fm_id_str}/tags"
        params = {"page_access_token": page_token}
        for headers in (
            {"Accept": "application/json", "Content-Type": "application/json"},
            {"Accept": "application/json"},
        ):
            _logger.info("Fetching v2 tags: %s params={'page_id': '%s'} headers=%s",
                         url, page.page_fm_id_str, list(headers.keys()))
            resp = requests.get(url, params=params, headers=headers, timeout=25)
            if not resp.ok:
                if resp.status_code not in (401, 403, 404, 406):
                    _logger.warning("Tags v2 HTTP %s: %s", resp.status_code, resp.text[:200])
                continue
            try:
                data = resp.json() if resp.text else {}
            except Exception:
                _logger.error("Tags v2 non-JSON (CT=%s): %s", resp.headers.get("Content-Type", ""), resp.text[:200])
                return []
            items = data.get("tags") or data.get("data") or []
            return self._parse_items_to_rows(items)
        return []

    def _collect_tags_from_conversations_api(self, page, page_token):
        """Fallback: gom tag_id từ conversations v2 (ít nhất có id, tên = id)."""
        base = f"{PAGES_FM_PUBLIC_API_V2_BASE_URL}/pages/{page.page_fm_id_str}/conversations"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        params = {"page_access_token": page_token}
        seen, out, last_id = set(), [], None
        while True:
            q = dict(params)
            if last_id:
                q["last_conversation_id"] = last_id
            resp = requests.get(base, headers=headers, params=q, timeout=25)
            if not resp.ok:
                _logger.warning("Fallback conversations v2 HTTP %s: %s", resp.status_code, resp.text[:200])
                break
            data = resp.json()
            convs = data.get("conversations") or []
            if not convs:
                break
            for c in convs:
                for t in (c.get("tags") or []):
                    tid = str(t).strip()
                    if tid and tid not in seen:
                        seen.add(tid)
                        out.append({"id": tid, "text": tid})
            if len(convs) < 60:
                break
            last_id = convs[-1].get("id")
        return out

    def _fetch_page_tags(self, page):
        """
        Lấy danh sách tag cho 1 page:
        1) v1 /tags (chính theo docs)
        2) v2 /tags (thử thêm)
        3) fallback: conversations v2
        """
        page_token = self._get_page_token(page)
        rows = self._fetch_page_tags_v1(page, page_token)
        if rows or rows == []:
            return rows
        rows = self._fetch_page_tags_v2(page, page_token)
        if rows or rows == []:
            return rows
        _logger.warning("V1/V2 /tags không dùng được, chuyển fallback conversations …")
        return self._collect_tags_from_conversations_api(page, page_token)

    # =========================== SYNC ===========================
    def action_sync_page_tags(self):
        """
        Đồng bộ danh sách tag cho các Page (từ context active_ids) hoặc toàn bộ Page.
        """
        Page = self.env["page.fm.page"].sudo()
        Tag = self.sudo()

        page_ids = self.env.context.get("active_ids")
        pages = Page.browse(page_ids) if page_ids else Page.search([])

        total_new = total_update = 0
        for page in pages:
            try:
                rows = self._fetch_page_tags(page)
            except Exception as e:
                _logger.error("Sync tags error for page %s: %s", page.id, e)
                continue

            for row in rows:
                tag_id = str(row.get("id") or "")
                text = str(row.get("text") or row.get("name") or tag_id)
                vals = {
                    "name": text,
                    "fm_text": text,
                    "tag_fm_id": tag_id,
                    "page_id": page.id,
                    "fm_color_hex": row.get("color"),
                    "fm_lighten_rgba": row.get("lighten_color"),
                    "fm_is_lead_event": bool(row.get("is_lead_event")),
                    "active": True,
                }
                rec = Tag.search([("page_id", "=", page.id), ("tag_fm_id", "=", tag_id)], limit=1)
                if rec:
                    rec.write(vals); total_update += 1
                else:
                    Tag.create(vals); total_new += 1

        _logger.info("SYNC TAGS DONE: created=%s, updated=%s", total_new, total_update)
        return True

    # ========================= Seed bo tag chuan ==========================
    # (name_pattern_lower, odoo_tag_code, display_name, managed_by_ai)
    _STANDARD_TAG_SEED = [
        ('cần xử lý',         'needs_action',                 'Cần xử lý',          True),
        ('chờ khách phản hồi', 'waiting_customer_reply', 'Chờ khách phản hồi', True),
        ('chăm lại',           'recontact_needed',             'Chăm lại',           True),
        ('chưa thu tiền',       'payment_due_after_production', 'Chưa thu tiền',      True),
        ('đã mua hàng',        'customer_purchased',           'Đã mua hàng',         True),
        ('khách quen',          'customer_repeat',              'Khách quen',          True),
        ('fail',               'lost_or_cold',                 'Fail',                True),
        ('done',               'done',                         'Done',                True),
        ('khách lớn',          'customer_vip',                 'Khách lớn',          False),
    ]

    @api.model
    def action_seed_standard_tag_codes(self, dry_run=False, page_ids=None):
        """Seed odoo_tag_code cho tag hien co va tao tag con thieu.

        An toan: chi ghi khi can, khong xoa tag cu.
        dry_run=True => chi tra bao cao, khong ghi.
        page_ids => gioi han page; None = toan bo page.
        """
        Page = self.env['page.fm.page'].sudo()
        Tag = self.sudo()

        pages = Page.browse(page_ids) if page_ids else Page.search([])
        if not pages:
            return {'pages_processed': 0, 'mapped': [], 'created': [], 'skipped': [], 'dry_run': dry_run}

        report = {'pages_processed': 0, 'mapped': [], 'created': [], 'skipped': [], 'dry_run': dry_run}

        for page in pages:
            report['pages_processed'] += 1
            for name_pattern, code, display_name, ai_flag in self._STANDARD_TAG_SEED:
                # 1) Da co tag voi dung code -> cap nhat managed_by_ai neu lech
                existing_by_code = Tag.search([
                    ('page_id', '=', page.id),
                    ('odoo_tag_code', '=', code),
                ], limit=1)
                if existing_by_code:
                    if existing_by_code.managed_by_ai != ai_flag:
                        if not dry_run:
                            existing_by_code.write({'managed_by_ai': ai_flag})
                        report['mapped'].append({
                            'page': page.name, 'code': code,
                            'action': 'update_ai_flag', 'tag': existing_by_code.name,
                        })
                    else:
                        report['skipped'].append({'page': page.name, 'code': code, 'reason': 'already_set'})
                    continue

                # 2) Chua co code -> tim tag theo ten
                all_page_tags = Tag.search([('page_id', '=', page.id), ('active', '=', True)])
                matched = all_page_tags.filtered(
                    lambda t, p=name_pattern: (
                        (t.name or '').strip().lower() == p
                        or (t.fm_text or '').strip().lower() == p
                    )
                )
                if matched:
                    tag = matched[0]
                    if not dry_run:
                        tag.write({'odoo_tag_code': code, 'odoo_tag_label': display_name, 'managed_by_ai': ai_flag})
                    report['mapped'].append({
                        'page': page.name, 'code': code,
                        'action': 'mapped', 'tag': tag.name, 'tag_id': tag.id,
                    })
                    continue

                # 3) Khong tim thay -> tao local tag
                if not dry_run:
                    Tag.create({
                        'name': display_name,
                        'fm_text': display_name,
                        'tag_fm_id': 'local::' + code,
                        'page_id': page.id,
                        'odoo_tag_code': code,
                        'odoo_tag_label': display_name,
                        'managed_by_ai': ai_flag,
                    })
                report['created'].append({'page': page.name, 'code': code, 'name': display_name})

        _logger.info(
            "SEED TAG CODES: pages=%s mapped=%s created=%s skipped=%s dry_run=%s",
            report['pages_processed'], len(report['mapped']), len(report['created']),
            len(report['skipped']), dry_run,
        )
        return report

    # Tiện ích: tìm/tạo nhanh theo mã nội bộ trong 1 Page
    @api.model
    def find_or_create_by_code(self, page, code, default_name=None):
        code = (code or "").strip()
        if not code:
            return False
        rec = self.search([("page_id", "=", page.id), ("odoo_tag_code", "=", code)], limit=1)
        if rec:
            return rec
        return self.create({
            "name": default_name or code,
            "fm_text": default_name or code,
            "tag_fm_id": f"local::{code}",  # đánh dấu là mã nội bộ
            "page_id": page.id,
            "odoo_tag_code": code,
            "odoo_tag_label": default_name or code,
        })


class PageFmPage(models.Model):
    """Bổ sung nút tiện ích trên Page để sync nhanh (multi-record)."""
    _inherit = "page.fm.page"

    def action_sync_tags(self):
        pages = self.sudo()
        if not pages:
            return False
        # chạy sync cho tất cả page đang được chọn/mở
        self.env["page.fm.tag"].with_context(active_ids=pages.ids).action_sync_page_tags()
        # mở list Tag lọc theo page
        action = self.env.ref("CRM_DAC.action_page_fm_tag").read()[0]
        action["domain"] = [("page_id", "=", pages.id)] if len(pages) == 1 else [("page_id", "in", pages.ids)]
        return action
