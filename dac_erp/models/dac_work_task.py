import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ── Config param keys ────────────────────────────────────────────────────
_ICP_COOLDOWN = 'dac_erp.openclaw_reminder_cooldown_minutes'
_ICP_WARNING_WINDOW = 'dac_erp.openclaw_deadline_warning_window_minutes'
_ICP_BATCH_LIMIT = 'dac_erp.openclaw_reminder_batch_limit'
_ICP_WARNING_ENABLED = 'dac_erp.openclaw_enable_deadline_warning'

_DEFAULT_COOLDOWN = 60       # minutes — minimum gap between two reminders for the same task
_DEFAULT_WINDOW = 120        # minutes — how far ahead to warn about an upcoming deadline
_DEFAULT_BATCH = 100         # max tasks processed per cron run (each category)
_LOOKBACK_HOURS = 48         # ignore overdue tasks older than this (avoid blast after downtime)

# Fields on sale.order whose changes should trigger task snapshot refresh + task.context_updated event
_SNAPSHOT_CONTEXT_FIELDS = frozenset({
    'order_title', 'order_summary', 'design_deadline', 'production_deadline',
    'design_link', 'delivery_address', 'installation_address',
    'is_priority', 'is_priority_today', 'fulfillment_method',
})


class DacWorkTask(models.Model):
    _name = 'dac.work.task'
    _description = 'DAC Work Task'
    _order = 'deadline asc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Tiêu đề', required=True, tracking=True)
    description = fields.Text(string='Mô tả')
    state = fields.Selection([
        ('draft', 'Chưa thực hiện'),
        ('in_progress', 'Đang làm'),
        ('done', 'Hoàn thành'),
        ('cancelled', 'Huỷ'),
    ], string='Trạng thái', default='draft', required=True, tracking=True)
    priority = fields.Selection([
        ('normal', 'Bình thường'),
        ('high', 'Cao'),
        ('urgent', 'Khẩn'),
    ], string='Ưu tiên', default='normal', required=True)
    task_type = fields.Selection([
        ('survey',      'Khảo sát'),
        ('supplement',  'Bổ sung yêu cầu'),
        ('design',      'Thiết kế'),
        ('production',  'Thi công / Sản xuất'),
        ('other',       'Khác'),
    ], string='Loại công việc', default='other', index=True)
    deadline = fields.Datetime(string='Hạn chót', tracking=True)
    remind_at = fields.Datetime(string='Nhắc lúc', tracking=True)

    order_id = fields.Many2one(
        'sale.order', string='Đơn hàng', index=True, ondelete='set null',
    )
    partner_id = fields.Many2one(
        'res.partner', related='order_id.partner_id',
        string='Khách hàng', store=False, readonly=True,
    )
    conversation_id = fields.Many2one(
        'page.fm.conversation', string='Hội thoại', index=True, ondelete='set null',
    )
    assigned_user_id = fields.Many2one(
        'res.users', string='Người thực hiện', tracking=True,
    )
    created_by_agent = fields.Char(
        string='Tạo bởi Agent', readonly=True,
    )
    notes = fields.Text(string='Ghi chú nội bộ')

    description_plain = fields.Char(
        string='Mô tả (1 dòng)',
        compute='_compute_description_plain',
        store=False,
    )

    days_left_display = fields.Char(
        string='Còn lại',
        compute='_compute_days_left_display',
        store=False,
    )

    @api.depends('description')
    def _compute_description_plain(self):
        from odoo.tools import html2plaintext
        for task in self:
            if task.description:
                text = html2plaintext(task.description).strip()
                first_line = next((l.strip() for l in text.splitlines() if l.strip()), '')
                task.description_plain = first_line[:200]
            else:
                task.description_plain = ''

    @api.depends('deadline', 'state')
    def _compute_days_left_display(self):
        now = fields.Datetime.now()
        for task in self:
            if task.state in ('done', 'cancelled'):
                task.days_left_display = '—'
            elif not task.deadline:
                task.days_left_display = 'Chưa có hạn'
            else:
                delta = (task.deadline.date() - now.date()).days
                if delta < 0:
                    task.days_left_display = f'Quá {abs(delta)} ngày'
                elif delta == 0:
                    task.days_left_display = 'Đến hạn hôm nay'
                else:
                    task.days_left_display = f'Còn {delta} ngày'

    # Timestamps ghi nhận lần cuối gửi từng loại thông báo
    x_openclaw_last_reminder_at = fields.Datetime(
        string='Lần cuối gửi reminder', copy=False,
        help='Thời điểm gửi task_reminder lần gần nhất (remind_at trigger hoặc overdue).',
    )
    x_openclaw_last_deadline_warning_at = fields.Datetime(
        string='Lần cuối gửi deadline warning', copy=False,
        help='Thời điểm gửi cảnh báo deadline sắp đến lần gần nhất.',
    )
    x_openclaw_last_escalation_at = fields.Datetime(
        string='Lần cuối gửi overdue escalation', copy=False,
    )

    # ── Personal reminder fields (Phần 6A) ──────────────────────────────
    is_personal_reminder = fields.Boolean(
        string='Nhắc việc cá nhân',
        default=False,
        index=True,
        copy=False,
        help='True khi task được tạo từ chat cá nhân (OpenClaw/MCP), '
             'không bắt buộc liên kết đơn hàng hay hội thoại.',
    )
    personal_reminder_source = fields.Char(
        string='Nguồn nhắc việc',
        copy=False,
        help='Ghi nhận nguồn tạo task cá nhân, ví dụ: openclaw_chat, mcp_api.',
    )

    # ── Snapshot fields — safe copy từ sale.order, KHÔNG chứa monetary data ──
    # copy=False: không nhân bản khi duplicate task
    # tracking=False: tránh chatter spam khi order thay đổi
    snap_order_title = fields.Char(string='[Snap] Tiêu đề đơn', copy=False)
    snap_order_summary = fields.Text(string='[Snap] Tóm tắt đơn', copy=False)
    snap_order_number = fields.Char(string='[Snap] Số đơn', copy=False)
    snap_design_deadline = fields.Date(string='[Snap] Hạn thiết kế', copy=False)
    snap_design_link = fields.Char(string='[Snap] Link thiết kế', copy=False)
    snap_production_deadline = fields.Date(string='[Snap] Hạn sản xuất', copy=False)
    snap_delivery_address = fields.Text(string='[Snap] Địa chỉ giao hàng', copy=False)
    snap_installation_address = fields.Text(string='[Snap] Địa chỉ thi công', copy=False)
    snap_is_priority = fields.Boolean(string='[Snap] Ưu tiên', copy=False)
    snap_is_priority_today = fields.Boolean(string='[Snap] Ưu tiên hôm nay', copy=False)
    snap_fulfillment_method = fields.Char(string='[Snap] Hình thức', copy=False)
    snap_updated_at = fields.Datetime(string='[Snap] Cập nhật lúc', copy=False)
    # snap_contact_phone: chỉ populate khi task_type='production' + fulfillment in delivery/installation
    # Không copy snap_customer_phone tổng quát — tránh lộ PII cho design task
    snap_contact_phone = fields.Char(
        string='[Snap] SĐT liên hệ giao hàng', copy=False,
        help='Chỉ có khi task sản xuất + đơn có hình thức giao hàng/lắp đặt.',
    )

    # ── Blocker fields — overlay flag, không phải state ──────────────────
    is_blocked = fields.Boolean(
        string='Đang bị block', default=False, index=True, tracking=True, copy=False,
    )
    blocker_reason = fields.Text(string='Lý do block', copy=False)
    blocker_reported_at = fields.Datetime(string='Block lúc', copy=False)
    blocker_reported_by = fields.Many2one(
        'res.users', string='Người báo block', copy=False, ondelete='set null',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'name' in fields_list and not res.get('name') and res.get('order_id'):
            order = self.env['sale.order'].browse(res['order_id'])
            if order.exists():
                res['name'] = order.order_title or order.name or ''
        return res

    @api.constrains('order_id', 'conversation_id', 'is_personal_reminder')
    def _check_requires_link(self):
        for rec in self:
            if not rec.is_personal_reminder and not rec.order_id and not rec.conversation_id:
                raise ValidationError(
                    'Task phải liên kết với ít nhất một đơn hàng hoặc một hội thoại.'
                )

    def _openclaw_active_task_domain(self):
        return [('state', 'not in', ['done', 'cancelled'])]

    # ══════════════════════════════════════════════════════════════════
    # Snapshot helpers — Option C (Hybrid Snapshot + Link)
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _build_snapshot_vals(self, order, task_type):
        """Trả về dict snapshot safe fields từ order.

        KHÔNG bao giờ chứa monetary fields: amount_total, deposit_amount,
        price_unit, amount_untaxed, promotion_amount, remaining_amount_display, ...
        snap_contact_phone chỉ populate cho production task khi fulfillment cần giao/lắp.
        """
        vals = {
            'snap_order_title':        order.order_title or order.name or '',
            'snap_order_summary':      getattr(order, 'order_summary', '') or '',
            'snap_order_number':       getattr(order, 'order_number', None) or order.name or '',
            'snap_design_deadline':    order.design_deadline or False,
            'snap_design_link':        getattr(order, 'design_link', None) or '',
            'snap_production_deadline': order.production_deadline or False,
            'snap_delivery_address':   getattr(order, 'delivery_address', None) or '',
            'snap_installation_address': getattr(order, 'installation_address', None) or '',
            'snap_is_priority':        bool(getattr(order, 'is_priority', False)),
            'snap_is_priority_today':  bool(getattr(order, 'is_priority_today', False)),
            'snap_fulfillment_method': getattr(order, 'fulfillment_method', '') or '',
            'snap_updated_at':         fields.Datetime.now(),
            'snap_contact_phone':      False,
        }
        # snap_contact_phone: chỉ expose khi production task + fulfillment giao/lắp
        fulfillment = vals['snap_fulfillment_method']
        if task_type == 'production' and fulfillment in ('delivery', 'installation'):
            partner = order.partner_id
            if partner:
                vals['snap_contact_phone'] = partner.phone or partner.mobile or False
        return vals

    @api.model
    def _create_from_order(self, order, task_type, assigned_user_id=None,
                           deadline=None, priority='normal', notes='',
                           created_by_agent='sale_assignment'):
        """Ensure-or-create task cho một order.

        Idempotency: nếu đã có active task cùng order + type + agent, return existing.
        Returns (task, was_created: bool).
        """
        domain = [
            ('order_id', '=', order.id),
            ('task_type', '=', task_type),
            ('created_by_agent', '=', created_by_agent),
            ('state', 'not in', ('done', 'cancelled')),
        ]
        existing = self.search(domain, limit=1)
        if existing:
            return existing, False

        type_labels = dict(self._fields['task_type'].selection)
        type_label = type_labels.get(task_type, task_type)
        order_ref = getattr(order, 'order_number', None) or order.name
        task_name = f'{type_label}: {order_ref}'

        snap = self._build_snapshot_vals(order, task_type)
        vals = {
            'name': task_name,
            'task_type': task_type,
            'order_id': order.id,
            'state': 'draft',
            'priority': priority,
            'notes': notes or '',
            'created_by_agent': created_by_agent,
            **snap,
        }
        if assigned_user_id:
            vals['assigned_user_id'] = assigned_user_id
        if deadline:
            vals['deadline'] = deadline

        task = self.create([vals])
        return task, True

    def _refresh_snapshot(self):
        """Re-sync snapshot từ order hiện tại. Gọi khi order thay đổi _SNAPSHOT_CONTEXT_FIELDS."""
        for task in self:
            if not task.order_id:
                continue
            snap_vals = self._build_snapshot_vals(task.order_id, task.task_type)
            # dac_skip_order_sync: tránh trigger _sync_to_sale_order ngược lại
            task.with_context(dac_skip_order_sync=True).write(snap_vals)

    # ══════════════════════════════════════════════════════════════════
    # ORM hooks — task_assigned notification
    # ══════════════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            if task.assigned_user_id:
                task._send_task_assigned_notification()
        return tasks

    def write(self, vals):
        # Blocker guard: cannot block terminal tasks
        if vals.get('is_blocked') is True:
            terminal = self.filtered(lambda t: t.state in ('done', 'cancelled'))
            if terminal:
                raise ValidationError(
                    'Không thể block task đã hoàn thành hoặc huỷ: '
                    + ', '.join(terminal.mapped('name'))
                )

        # Blocker guard: cannot mark done while blocked
        if vals.get('state') == 'done':
            blocked = self.filtered(lambda t: t.is_blocked)
            if blocked:
                raise ValidationError(
                    'Task đang bị block — xoá blocker trước khi đánh dấu hoàn thành: '
                    + ', '.join(blocked.mapped('name'))
                )

        skip_order_sync = self.env.context.get('dac_skip_order_sync')

        track_assigned = 'assigned_user_id' in vals
        track_state = 'state' in vals
        track_deadline = 'deadline' in vals

        old_assigned = {t.id: t.assigned_user_id.id for t in self} if track_assigned else {}
        old_state = {t.id: t.state for t in self} if track_state else {}
        old_deadline = {t.id: t.deadline for t in self} if track_deadline else {}

        result = super().write(vals)

        if track_assigned:
            for task in self:
                new_uid = task.assigned_user_id.id
                if new_uid and new_uid != old_assigned.get(task.id):
                    task._send_task_assigned_notification()

        if not skip_order_sync and (track_state or track_deadline):
            self._sync_to_sale_order(old_state, old_deadline,
                                     track_state=track_state,
                                     track_deadline=track_deadline)
        return result

    def _sync_to_sale_order(self, old_state, old_deadline,
                            track_state=False, track_deadline=False):
        """Đồng bộ trạng thái/deadline của task sản xuất/thiết kế ngược về sale.order.

        Áp dụng cho task được tạo bởi 'Phân công sản xuất/thiết kế'
        (created_by_agent='sale_assignment') với task_type in ('production','design').
        """
        now = fields.Datetime.now()
        for task in self:
            if not task.order_id or task.created_by_agent != 'sale_assignment':
                continue
            if task.task_type not in ('production', 'design'):
                continue

            order = task.order_id
            order_ctx = order.sudo().with_context(dac_skip_task_sync=True)

            # 1) Sync deadline task → order
            if track_deadline and task.deadline != old_deadline.get(task.id):
                new_date = task.deadline.date() if task.deadline else False
                if task.task_type == 'production':
                    if order.production_deadline != new_date:
                        order_ctx.write({'production_deadline': new_date})
                else:  # design
                    if order.design_deadline != new_date:
                        order_ctx.write({'design_deadline': new_date})

            # 2) Auto-mark order done khi task chuyển sang 'done'
            if track_state and task.state == 'done' and old_state.get(task.id) != 'done':
                if task.task_type == 'production' and not order.production_done:
                    order_ctx.write({
                        'production_done': True,
                        'production_done_date': now,
                        'production_done_user_id': self.env.user.id,
                    })
                    order.message_post(
                        body=(
                            f"Task sản xuất <b>{task.name}</b> đã hoàn thành "
                            f"→ đơn tự động chuyển sang <b>Hoàn tất sản xuất</b>."
                        ),
                        subtype_xmlid='mail.mt_note',
                    )
                elif task.task_type == 'design' and not order.design_done:
                    order_ctx.write({
                        'design_done': True,
                        'design_done_date': now,
                        'design_done_user_id': self.env.user.id,
                    })
                    order.message_post(
                        body=(
                            f"Task thiết kế <b>{task.name}</b> đã hoàn thành "
                            f"→ đơn tự động chuyển sang <b>Hoàn tất thiết kế</b>."
                        ),
                        subtype_xmlid='mail.mt_note',
                    )

    def _send_task_assigned_notification(self):
        self.ensure_one()
        if not self.assigned_user_id:
            return
        Mapping = self.env['dac.openclaw.user.mapping'].sudo()
        service = self.env['dac.openclaw.notification.service']
        mappings = Mapping._get_employee_delivery_mapping(self.assigned_user_id, notify_type='notify')
        for mapping in mappings:
            payload = service._build_openclaw_payload(self, mapping)
            service._send_openclaw_webhook('task_assigned', payload, task=self, mapping=mapping)

    # ══════════════════════════════════════════════════════════════════
    # Config helpers
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_reminder_cooldown(self):
        """Minutes between re-sends for the same task. Default: 60."""
        raw = self.env['ir.config_parameter'].sudo().get_param(_ICP_COOLDOWN, str(_DEFAULT_COOLDOWN))
        try:
            return max(1, int(raw))
        except Exception:
            return _DEFAULT_COOLDOWN

    @api.model
    def _get_deadline_warning_window(self):
        """How many minutes ahead to warn about an upcoming deadline. Default: 120."""
        raw = self.env['ir.config_parameter'].sudo().get_param(_ICP_WARNING_WINDOW, str(_DEFAULT_WINDOW))
        try:
            return max(1, int(raw))
        except Exception:
            return _DEFAULT_WINDOW

    @api.model
    def _get_reminder_batch_limit(self):
        """Max tasks per cron pass per category. Default: 100."""
        raw = self.env['ir.config_parameter'].sudo().get_param(_ICP_BATCH_LIMIT, str(_DEFAULT_BATCH))
        try:
            return max(1, int(raw))
        except Exception:
            return _DEFAULT_BATCH

    @api.model
    def _deadline_warning_enabled(self):
        """Feature flag for deadline warning. Default: enabled."""
        val = self.env['ir.config_parameter'].sudo().get_param(_ICP_WARNING_ENABLED, '1')
        return str(val).strip() not in ('0', 'false', 'False', '')

    # ══════════════════════════════════════════════════════════════════
    # Business guards — callable from shell for ad-hoc checks
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _should_send_reminder(self, task, now=None):
        """Return True if task qualifies for a remind_at / overdue reminder right now.

        Mirrors the SQL domain in _get_due_tasks_for_reminder so callers can
        test a single task from the shell:
            env['dac.work.task']._should_send_reminder(task)
        """
        now = now or fields.Datetime.now()
        if not task.assigned_user_id:
            return False
        if task.state in ('done', 'cancelled'):
            return False
        cooldown_threshold = now - timedelta(minutes=self._get_reminder_cooldown())
        if task.x_openclaw_last_reminder_at and task.x_openclaw_last_reminder_at >= cooldown_threshold:
            return False
        cutoff = now - timedelta(hours=_LOOKBACK_HOURS)
        if task.remind_at:
            return cutoff <= task.remind_at <= now
        if task.deadline:
            return cutoff <= task.deadline <= now
        return False

    @api.model
    def _should_send_deadline_warning(self, task, now=None):
        """Return True if task qualifies for a deadline-approaching warning right now.

        Shell usage:
            env['dac.work.task']._should_send_deadline_warning(task)
        """
        now = now or fields.Datetime.now()
        if not task.assigned_user_id:
            return False
        if task.state in ('done', 'cancelled'):
            return False
        if not task.deadline:
            return False
        window_end = now + timedelta(minutes=self._get_deadline_warning_window())
        # Deadline must be strictly in the future but within the warning window
        if not (now < task.deadline <= window_end):
            return False
        cooldown_threshold = now - timedelta(minutes=self._get_reminder_cooldown())
        if (task.x_openclaw_last_deadline_warning_at
                and task.x_openclaw_last_deadline_warning_at >= cooldown_threshold):
            return False
        return True

    # ══════════════════════════════════════════════════════════════════
    # SQL query helpers
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_due_tasks_for_reminder(self, now=None, limit=None):
        """Return tasks eligible for remind_at or overdue reminder.

        Two paths (unioned):
          A) remind_at is set AND remind_at <= now (within 48h lookback)
          B) No remind_at, deadline <= now (within 48h lookback)
        Both filtered by cooldown on x_openclaw_last_reminder_at.
        """
        now = now or fields.Datetime.now()
        cutoff = now - timedelta(hours=_LOOKBACK_HOURS)
        cooldown_threshold = now - timedelta(minutes=self._get_reminder_cooldown())

        cooldown_clause = [
            '|',
            ('x_openclaw_last_reminder_at', '=', False),
            ('x_openclaw_last_reminder_at', '<', cooldown_threshold),
        ]
        base = [
            ('state', 'not in', ['done', 'cancelled']),
            ('assigned_user_id', '!=', False),
        ] + cooldown_clause

        domain_remind = base + [
            ('remind_at', '!=', False),
            ('remind_at', '<=', now),
            ('remind_at', '>=', cutoff),
        ]
        domain_deadline = base + [
            ('remind_at', '=', False),
            ('deadline', '!=', False),
            ('deadline', '<=', now),
            ('deadline', '>=', cutoff),
        ]
        tasks_r = self.sudo().search(domain_remind, order='id asc')
        tasks_d = self.sudo().search(domain_deadline, order='id asc')
        combined = tasks_r | tasks_d
        return combined[:limit] if limit else combined

    @api.model
    def _get_due_tasks_for_deadline_warning(self, now=None, limit=None):
        """Return tasks whose deadline is approaching within the warning window.

        Only tasks where deadline is strictly in the future and within
        `openclaw_deadline_warning_window_minutes`. Cooldown uses
        x_openclaw_last_deadline_warning_at.
        """
        now = now or fields.Datetime.now()
        window_end = now + timedelta(minutes=self._get_deadline_warning_window())
        cooldown_threshold = now - timedelta(minutes=self._get_reminder_cooldown())

        cooldown_clause = [
            '|',
            ('x_openclaw_last_deadline_warning_at', '=', False),
            ('x_openclaw_last_deadline_warning_at', '<', cooldown_threshold),
        ]
        domain = [
            ('state', 'not in', ['done', 'cancelled']),
            ('assigned_user_id', '!=', False),
            ('deadline', '!=', False),
            ('deadline', '>', now),
            ('deadline', '<=', window_end),
        ] + cooldown_clause
        return self.sudo().search(domain, limit=limit, order='deadline asc, id asc')

    # ══════════════════════════════════════════════════════════════════
    # Mark-sent helpers
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _mark_task_reminder_sent(self, task, sent_at=None):
        task.sudo().write({'x_openclaw_last_reminder_at': sent_at or fields.Datetime.now()})

    @api.model
    def _mark_task_deadline_warning_sent(self, task, sent_at=None):
        task.sudo().write({'x_openclaw_last_deadline_warning_at': sent_at or fields.Datetime.now()})

    # ══════════════════════════════════════════════════════════════════
    # Processing helpers — one per reminder category
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _process_openclaw_task_reminders(self, now=None, limit=None):
        """Process remind_at + overdue reminders. Returns stats dict."""
        now = now or fields.Datetime.now()
        Mapping = self.env['dac.openclaw.user.mapping'].sudo()
        service = self.env['dac.openclaw.notification.service']
        tasks = self._get_due_tasks_for_reminder(now=now, limit=limit)
        stats = {'scanned': len(tasks), 'sent': 0, 'failed': 0, 'skipped': 0}

        for task in tasks:
            if not self._should_send_reminder(task, now=now):
                stats['skipped'] += 1
                continue
            mappings = Mapping._get_employee_delivery_mapping(
                task.assigned_user_id, notify_type='deadline',
            )
            
            sent_any = False
            if mappings:
                for mapping in mappings:
                    payload = service._build_openclaw_payload(task, mapping)
                    ok = service._send_openclaw_webhook(
                        'task_reminder', payload, task=task, mapping=mapping,
                    )
                    if ok:
                        sent_any = True
            
            if sent_any or not mappings:
                # Mark as sent so we don't process it repeatedly
                self._mark_task_reminder_sent(task, sent_at=now)
                if sent_any:
                    stats['sent'] += 1
                else:
                    stats['skipped'] += 1
                
                # Automatically reactivate linked conversation when reminder is triggered
                if task.conversation_id:
                    task.conversation_id.sudo().write({
                        'status_state': 'recontact',
                        'require_processing': True,
                    })
                    try:
                        task.conversation_id.sudo()._sync_tags_to_pancake(True)
                    except Exception as e:
                        _logger.warning("Error syncing tags to Pancake on task reminder for task %s: %s", task.id, e)
            else:
                stats['failed'] += 1

        return stats

    @api.model
    def _process_openclaw_deadline_warnings(self, now=None, limit=None):
        """Process upcoming deadline warnings. Returns stats dict."""
        now = now or fields.Datetime.now()
        if not self._deadline_warning_enabled():
            return {'scanned': 0, 'sent': 0, 'failed': 0, 'skipped': 0}

        Mapping = self.env['dac.openclaw.user.mapping'].sudo()
        service = self.env['dac.openclaw.notification.service']
        tasks = self._get_due_tasks_for_deadline_warning(now=now, limit=limit)
        stats = {'scanned': len(tasks), 'sent': 0, 'failed': 0, 'skipped': 0}

        for task in tasks:
            if not self._should_send_deadline_warning(task, now=now):
                stats['skipped'] += 1
                continue
            mappings = Mapping._get_employee_delivery_mapping(
                task.assigned_user_id, notify_type='deadline',
            )
            if not mappings:
                stats['skipped'] += 1
                continue
            sent_any = False
            for mapping in mappings:
                payload = service._build_openclaw_payload(task, mapping)
                ok = service._send_openclaw_webhook(
                    'task_reminder', payload, task=task, mapping=mapping,
                )
                if ok:
                    sent_any = True
            if sent_any:
                self._mark_task_deadline_warning_sent(task, sent_at=now)
                stats['sent'] += 1
            else:
                stats['failed'] += 1

        return stats

    # ══════════════════════════════════════════════════════════════════
    # Cron entry point
    # ══════════════════════════════════════════════════════════════════

    def cron_send_openclaw_deadline_reminders(self):
        now = fields.Datetime.now()
        limit = self._get_reminder_batch_limit()
        stats_r = self._process_openclaw_task_reminders(now=now, limit=limit)
        stats_w = self._process_openclaw_deadline_warnings(now=now, limit=limit)
        _logger.info(
            'openclaw cron | reminders: scanned=%d sent=%d failed=%d skipped=%d'
            ' | deadline_warnings: scanned=%d sent=%d failed=%d skipped=%d',
            stats_r['scanned'], stats_r['sent'], stats_r['failed'], stats_r['skipped'],
            stats_w['scanned'], stats_w['sent'], stats_w['failed'], stats_w['skipped'],
        )

    # ══════════════════════════════════════════════════════════════════
    # Legacy cron — daily digest (unchanged, uses legacy sender API)
    # ══════════════════════════════════════════════════════════════════

    def cron_send_openclaw_daily_digest(self):
        Mapping = self.env['dac.openclaw.user.mapping'].sudo()
        service = self.env['dac.openclaw.notification.service']
        mappings = Mapping.search([
            ('active', '=', True),
            ('notify_enabled', '=', True),
            ('digest_enabled', '=', True),
        ])
        for mapping in mappings:
            tasks = self.sudo().search([
                ('assigned_user_id', '=', mapping.user_id.id),
                ('state', 'in', ['draft', 'in_progress']),
            ], order='deadline asc, id desc')
            if not tasks:
                continue
            summary = {
                'total': len(tasks),
                'overdue': len(tasks.filtered(lambda t: t.deadline and t.deadline < fields.Datetime.now())),
                'urgent': len(tasks.filtered(lambda t: t.priority == 'urgent')),
                'due_today': len(tasks.filtered(lambda t: t.deadline and t.deadline.date() == fields.Datetime.now().date())),
            }
            payload = service.build_payload(
                event_type='daily_digest',
                mapping=mapping,
                tasks=tasks,
                summary=summary,
                event_id=service.build_event_id('daily_digest', mapping, suffix=fields.Date.today().strftime('%Y%m%d')),
            )
            service.send_payload('/hooks/odoo-daily-digest', payload, mapping=mapping)

    # ══════════════════════════════════════════════════════════════════
    # Legacy cron — overdue escalation (unchanged, uses legacy sender API)
    # ══════════════════════════════════════════════════════════════════

    def cron_send_openclaw_overdue_escalations(self):
        Mapping = self.env['dac.openclaw.user.mapping'].sudo()
        service = self.env['dac.openclaw.notification.service']
        now = fields.Datetime.now()
        overdue_tasks = self.sudo().search([
            ('deadline', '!=', False),
            ('deadline', '<', now),
            ('state', 'not in', ['done', 'cancelled']),
        ])
        manager_mappings = Mapping.search([
            ('active', '=', True),
            ('notify_enabled', '=', True),
            ('role', 'in', ['manager', 'admin']),
        ])
        for mapping in manager_mappings:
            scope_user_ids = mapping.get_scope_user_ids(include_self=False)
            if scope_user_ids is not None:
                tasks = overdue_tasks.filtered(lambda t: t.assigned_user_id.id in scope_user_ids)
            else:
                tasks = overdue_tasks
            tasks = tasks.filtered(lambda t: not t.x_openclaw_last_escalation_at)
            if not tasks:
                continue
            summary = {
                'total': len(tasks),
                'overdue': len(tasks),
                'urgent_overdue': len(tasks.filtered(lambda t: t.priority == 'urgent')),
                'employee_count': len(set(tasks.mapped('assigned_user_id').ids)),
            }
            payload = service.build_payload(
                event_type='task_escalation',
                mapping=mapping,
                tasks=tasks,
                summary=summary,
                event_id=service.build_event_id('task_escalation', mapping, suffix=fields.Date.today().strftime('%Y%m%d')),
            )
            log = service.send_payload('/hooks/odoo-escalation', payload, mapping=mapping)
            if log.status == 'sent':
                tasks.write({'x_openclaw_last_escalation_at': now})

    # ══════════════════════════════════════════════════════════════════
    # Phần 5: Manager digest cron entry point
    # ══════════════════════════════════════════════════════════════════

    def cron_send_openclaw_manager_digest(self):
        """Cron 2x/ngày — delegates sang dac.openclaw.manager.digest.service."""
        self.env['dac.openclaw.manager.digest.service'].cron_send_openclaw_manager_digest()

    # ══════════════════════════════════════════════════════════════════
    # UI actions
    # ══════════════════════════════════════════════════════════════════

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_set_urgent(self):
        for task in self:
            task.priority = 'normal' if task.priority == 'urgent' else 'urgent'

    def action_open_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
