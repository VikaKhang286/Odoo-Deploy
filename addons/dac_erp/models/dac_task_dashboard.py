from odoo import models, fields, api


class DacTaskDashboard(models.TransientModel):
    _name = 'dac.task.dashboard'
    _description = 'Dashboard Quản lý Công việc'

    # ── KPI stats ────────────────────────────────────────────────────────
    total_tasks = fields.Integer(string='Tổng đang hoạt động', readonly=True)
    my_tasks_count = fields.Integer(string='Việc của tôi', readonly=True)
    draft_count = fields.Integer(string='Chờ làm', readonly=True)
    in_progress_count = fields.Integer(string='Đang làm', readonly=True)
    done_count = fields.Integer(string='Hoàn thành', readonly=True)
    overdue_count = fields.Integer(string='Quá hạn', readonly=True)
    urgent_count = fields.Integer(string='Khẩn cấp', readonly=True)

    # ── Manager-only ─────────────────────────────────────────────────────
    is_manager = fields.Boolean(string='Là quản lý', readonly=True)
    employee_stats_html = fields.Html(
        string='Thống kê theo nhân viên', readonly=True, sanitize=False,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.update(self._build_dashboard_values())
        return values

    @api.model
    def _build_dashboard_values(self):
        is_manager = self.env.user.has_group('dac_erp.group_dac_erp_manager')
        # sudo: dashboard reads tasks across all users regardless of record rules
        Task = self.env['dac.work.task'].sudo()
        now = fields.Datetime.now()

        active_states = [('state', 'not in', ['done', 'cancelled'])]
        my_domain = [('assigned_user_id', '=', self.env.uid)]
        all_domain = [] if is_manager else my_domain

        values = {
            'is_manager': is_manager,
            'my_tasks_count': Task.search_count(my_domain + active_states),
            'total_tasks': Task.search_count(all_domain + active_states),
            'draft_count': Task.search_count(all_domain + [('state', '=', 'draft')]),
            'in_progress_count': Task.search_count(all_domain + [('state', '=', 'in_progress')]),
            'done_count': Task.search_count(all_domain + [('state', '=', 'done')]),
            'overdue_count': Task.search_count(
                all_domain + active_states + [
                    ('deadline', '!=', False),
                    ('deadline', '<', now),
                ]
            ),
            'urgent_count': Task.search_count(
                all_domain + active_states + [('priority', '=', 'urgent')]
            ),
        }
        if is_manager:
            values['employee_stats_html'] = self._build_employee_stats_html()
        return values

    @api.model
    def _build_employee_stats_html(self):
        # sudo: manager view spans all users' tasks
        data = self.env['dac.work.task'].sudo().read_group(
            domain=[('assigned_user_id', '!=', False)],
            fields=['assigned_user_id', 'state'],
            groupby=['assigned_user_id', 'state'],
            lazy=False,
        )
        if not data:
            return '<p class="text-muted p-3">Chưa có task nào được giao cho nhân viên.</p>'

        user_stats = {}
        for row in data:
            if not row.get('assigned_user_id'):
                continue
            uid, uname = row['assigned_user_id']
            if uid not in user_stats:
                user_stats[uid] = {
                    'name': uname,
                    'draft': 0, 'in_progress': 0, 'done': 0, 'cancelled': 0,
                }
            state = row.get('state') or 'draft'
            if state in user_stats[uid]:
                user_stats[uid][state] = row['__count']

        rows = ''
        for uid, s in sorted(user_stats.items(), key=lambda x: x[1]['name']):
            active = s['draft'] + s['in_progress']
            total = active + s['done'] + s['cancelled']
            urgency_class = ' class="o_dac_task_row_busy"' if active >= 5 else ''
            rows += (
                f'<tr{urgency_class}>'
                f'<td class="o_dac_tbl_name">{s["name"]}</td>'
                f'<td class="text-center fw-bold">{total}</td>'
                f'<td class="text-center o_dac_state_draft">{s["draft"]}</td>'
                f'<td class="text-center o_dac_state_inprogress">{s["in_progress"]}</td>'
                f'<td class="text-center o_dac_state_done">{s["done"]}</td>'
                f'<td class="text-center text-muted">{s["cancelled"]}</td>'
                f'</tr>'
            )

        return (
            '<table class="o_dac_task_employee_table table table-sm table-hover mb-0">'
            '<thead><tr>'
            '<th>Nhân viên</th>'
            '<th class="text-center">Tổng</th>'
            '<th class="text-center">Nháp</th>'
            '<th class="text-center">Đang làm</th>'
            '<th class="text-center">Hoàn thành</th>'
            '<th class="text-center">Đã huỷ</th>'
            '</tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table>'
        )

    def action_refresh(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_my_tasks(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Việc của tôi',
            'res_model': 'dac.work.task',
            'view_mode': 'kanban,list,form',
            'domain': [('assigned_user_id', '=', self.env.uid)],
        }

    def action_open_all_tasks(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tất cả công việc',
            'res_model': 'dac.work.task',
            'view_mode': 'kanban,list,form',
        }

    def action_open_overdue_tasks(self):
        now = fields.Datetime.now()
        domain = [
            ('deadline', '!=', False),
            ('deadline', '<', now),
            ('state', 'not in', ['done', 'cancelled']),
        ]
        if not self.is_manager:
            domain += [('assigned_user_id', '=', self.env.uid)]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Task quá hạn',
            'res_model': 'dac.work.task',
            'view_mode': 'list,form',
            'domain': domain,
        }
