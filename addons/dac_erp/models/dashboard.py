from odoo import api, fields, models, _
from odoo.tools import html2plaintext
from datetime import timedelta
from odoo.exceptions import AccessError


def _first_line(html_or_text):
    if not html_or_text:
        return ''
    text = html2plaintext(html_or_text).strip()
    first = next((l.strip() for l in text.splitlines() if l.strip()), '')
    return first[:200]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_partner_vip_class(self, partner):
        if not partner or not partner.pancake_tag_ids:
            return ''
        tag_names = [tag.name.lower() for tag in partner.pancake_tag_ids]
        classes = []
        if 'khách lớn' in tag_names or 'vip' in tag_names:
            classes.append('vip-customer')
        if 'khách quen' in tag_names or 'loyal' in tag_names:
            classes.append('loyal-customer')
        return ' '.join(classes)

    def _get_task_dashboard_data(self, user_id):
        """Lấy task stats và task list cho dashboard Design/Production."""
        now = fields.Datetime.now()
        Task = self.env['dac.work.task'].sudo()

        active_tasks = Task.search([
            ('assigned_user_id', '=', user_id),
            ('state', 'not in', ['done', 'cancelled']),
        ], order='deadline asc nulls last, priority desc')

        week_ago = now - timedelta(days=7)
        done_count = Task.search_count([
            ('assigned_user_id', '=', user_id),
            ('state', '=', 'done'),
            ('write_date', '>=', fields.Datetime.to_string(week_ago)),
        ])

        overdue_count = sum(1 for t in active_tasks if t.deadline and t.deadline < now)
        due_soon_count = sum(
            1 for t in active_tasks
            if t.deadline and now <= t.deadline <= now + timedelta(hours=48)
        )
        urgent_count = sum(1 for t in active_tasks if t.priority == 'urgent')

        def _pack(t):
            dl = t.deadline
            is_overdue = bool(dl and dl < now)
            days_left = False
            if dl and not is_overdue:
                days_left = max(0, int((dl - now).total_seconds() / 86400))
            dl_str = False
            if dl:
                dl_loc = fields.Datetime.context_timestamp(self, dl)
                dl_str = dl_loc.strftime('%d/%m/%Y %H:%M')
            return {
                'id': t.id,
                'name': t.name or '',
                'task_type': t.task_type or 'other',
                'state': t.state,
                'priority': t.priority,
                'deadline_str': dl_str,
                'is_overdue': is_overdue,
                'days_left': days_left,
                'order_id': t.order_id.id if t.order_id else False,
                'order_name': t.order_id.name if t.order_id else False,
                'order_number': (t.order_id.order_number or False) if t.order_id else False,
                'order_title': (t.order_id.order_title or False) if t.order_id else False,
                'partner_name': t.order_id.partner_id.name if t.order_id else '',
                'description': _first_line(t.description),
            }

        buckets = {k: [] for k in ('design', 'production', 'survey', 'supplement', 'other')}
        all_packed = []
        for t in active_tasks:
            p = _pack(t)
            all_packed.append(p)
            ttype = p['task_type']
            buckets[ttype if ttype in buckets else 'other'].append(p)

        return {
            'task_stats': {
                'total': len(active_tasks),
                'overdue': overdue_count,
                'due_soon': due_soon_count,
                'done_week': done_count,
                'urgent': urgent_count,
            },
            'all_tasks': all_packed,
            'tasks_by_type': buckets,
        }

    @api.model
    def dac_get_dashboard_design(self):
        uid = self.env.uid
        user = self.env.user
        if not (user._dac_is_manager() or user._dac_is_design()):
            raise AccessError(_('Bạn không có quyền truy cập dashboard này.'))
        data = self._get_task_dashboard_data(uid)
        return {
            'task_stats': data['task_stats'],
            'design_tasks': data['all_tasks'],
            'user_name': user.name,
        }

    @api.model
    def dac_get_dashboard_production(self):
        uid = self.env.uid
        user = self.env.user
        if not (user._dac_is_manager() or user._dac_is_production()):
            raise AccessError(_('Bạn không có quyền truy cập dashboard sản xuất.'))
        data = self._get_task_dashboard_data(uid)
        b = data['tasks_by_type']
        return {
            'task_stats': data['task_stats'],
            'design_tasks': b['design'],
            'production_tasks': b['production'] + b['survey'] + b['supplement'] + b['other'],
            'user_name': user.name,
            'is_design_user': (user._dac_is_design() or user._dac_is_manager()),
        }
