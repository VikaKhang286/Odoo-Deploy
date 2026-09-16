import json
import logging
from datetime import timedelta, timezone as _dt_timezone

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_VN_TZ = _dt_timezone(timedelta(hours=7))
_STATES_TERMINAL = frozenset({'done', 'cancelled'})
_REMINDER_LOOKBACK_HOURS = 48   # must stay in sync with dac_work_task._LOOKBACK_HOURS
_SAMPLE_TASK_LIMIT = 5          # representative task IDs per user in output


class OpenclawSummaryService(models.AbstractModel):
    """Read-only aggregation service for task progress per employee.

    Produces a JSON-serializable dict summarising every employee's task
    workload in ~7 SQL queries (not N+1).  Callers:

        svc = env['dac.openclaw.summary.service']
        svc._get_task_progress_summary()                  # all users
        svc._get_user_task_progress_summary(user)         # single user
    """

    _name = 'dac.openclaw.summary.service'
    _description = 'OpenClaw Task Progress Summary Service'

    # ══════════════════════════════════════════════════════════════════
    # Config helpers
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_window_minutes(self):
        """Due-soon window (minutes). Reuses openclaw_deadline_warning_window_minutes. Default 120."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_deadline_warning_window_minutes', '120'
        )
        try:
            return max(1, int(raw))
        except Exception:
            return 120

    @api.model
    def _get_reminder_cooldown(self):
        """Reminder cooldown (minutes). Reuses openclaw_reminder_cooldown_minutes. Default 60."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'dac_erp.openclaw_reminder_cooldown_minutes', '60'
        )
        try:
            return max(1, int(raw))
        except Exception:
            return 60

    # ══════════════════════════════════════════════════════════════════
    # Serialization helper
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _to_vn_iso(self, dt):
        """Convert Odoo UTC-naive datetime → ISO 8601 string in +07:00."""
        if not dt:
            return None
        return dt.replace(tzinfo=_dt_timezone.utc).astimezone(_VN_TZ).isoformat()

    # ══════════════════════════════════════════════════════════════════
    # Aggregate fetchers — each issues 1 SQL query
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _fetch_state_counts(self, user_ids=None):
        """Return {uid_or_None: {state: count}} via a single GROUP BY query.

        uid_or_None is None for tasks with no assigned_user_id.
        When user_ids is provided, only those users are included (unassigned excluded).
        """
        Task = self.env['dac.work.task'].sudo()
        domain = [('assigned_user_id', 'in', list(user_ids))] if user_ids is not None else []

        groups = Task.read_group(
            domain=domain,
            fields=['assigned_user_id', 'state'],
            groupby=['assigned_user_id', 'state'],
            lazy=False,
        )
        result = {}
        for g in groups:
            uid = g['assigned_user_id'][0] if g['assigned_user_id'] else None
            result.setdefault(uid, {})[g['state']] = g['__count']
        return result

    @api.model
    def _fetch_overdue_counts(self, now, user_ids=None):
        """Return {uid_or_None: count} — active tasks whose deadline has passed."""
        Task = self.env['dac.work.task'].sudo()
        domain = [
            ('state', 'not in', list(_STATES_TERMINAL)),
            ('deadline', '!=', False),
            ('deadline', '<', now),
        ]
        if user_ids is not None:
            domain.append(('assigned_user_id', 'in', list(user_ids)))
        groups = Task.read_group(domain, ['assigned_user_id'], ['assigned_user_id'])
        return {
            (g['assigned_user_id'][0] if g['assigned_user_id'] else None): g['assigned_user_id_count']
            for g in groups
        }

    @api.model
    def _fetch_due_soon_counts(self, now, window_minutes, user_ids=None):
        """Return {uid_or_None: count} — active tasks with deadline in (now, now+window_minutes]."""
        Task = self.env['dac.work.task'].sudo()
        window_end = now + timedelta(minutes=window_minutes)
        domain = [
            ('state', 'not in', list(_STATES_TERMINAL)),
            ('deadline', '!=', False),
            ('deadline', '>', now),
            ('deadline', '<=', window_end),
        ]
        if user_ids is not None:
            domain.append(('assigned_user_id', 'in', list(user_ids)))
        groups = Task.read_group(domain, ['assigned_user_id'], ['assigned_user_id'])
        return {
            (g['assigned_user_id'][0] if g['assigned_user_id'] else None): g['assigned_user_id_count']
            for g in groups
        }

    @api.model
    def _fetch_reminder_due_counts(self, now, user_ids=None):
        """Return {uid_or_None: count} — tasks currently eligible for a reminder.

        Domain mirrors DacWorkTask._get_due_tasks_for_reminder so both surfaces
        show the same business logic.  Two read_group calls (remind_at path +
        deadline path) are merged into one dict.
        """
        Task = self.env['dac.work.task'].sudo()
        cooldown_threshold = now - timedelta(minutes=self._get_reminder_cooldown())
        cutoff = now - timedelta(hours=_REMINDER_LOOKBACK_HOURS)

        cooldown_clause = [
            '|',
            ('x_openclaw_last_reminder_at', '=', False),
            ('x_openclaw_last_reminder_at', '<', cooldown_threshold),
        ]
        base = [('state', 'not in', list(_STATES_TERMINAL))] + cooldown_clause
        if user_ids is not None:
            base.append(('assigned_user_id', 'in', list(user_ids)))

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

        counts = {}
        for domain in (domain_remind, domain_deadline):
            for g in Task.read_group(domain, ['assigned_user_id'], ['assigned_user_id']):
                uid = g['assigned_user_id'][0] if g['assigned_user_id'] else None
                counts[uid] = counts.get(uid, 0) + g['assigned_user_id_count']
        return counts

    @api.model
    def _fetch_next_values(self, now, user_ids=None):
        """Return {uid_or_None: {'next_deadline': dt|None, 'next_remind_at': dt|None}}.

        Uses raw SQL MIN aggregation — Odoo's read_group does not expose MIN
        on datetime fields without a computed stored field.
        Only looks at active tasks with future deadline / remind_at.
        """
        uid_filter_sql = ''
        params = [now, now]
        if user_ids is not None:
            uid_filter_sql = 'AND assigned_user_id = ANY(%s)'
            params.append(list(user_ids))

        self.env.cr.execute(
            f"""
            SELECT
                assigned_user_id,
                MIN(CASE WHEN deadline  > %s THEN deadline  END) AS next_deadline,
                MIN(CASE WHEN remind_at > %s THEN remind_at END) AS next_remind_at
            FROM dac_work_task
            WHERE state NOT IN ('done', 'cancelled')
              {uid_filter_sql}
            GROUP BY assigned_user_id
            """,
            params,
        )
        result = {}
        for uid, next_dl, next_ra in self.env.cr.fetchall():
            result[uid] = {'next_deadline': next_dl, 'next_remind_at': next_ra}
        return result

    @api.model
    def _fetch_sample_task_ids(self, user_ids=None, limit=_SAMPLE_TASK_LIMIT):
        """Return {uid_or_None: [task_id, ...]} — a few active task IDs per user.

        Loads at most 500 tasks in one query sorted by urgency (earliest deadline
        first), then slices per-user up to `limit` entries.  The 500-row cap is
        intentional: this is representative sample data, not an exhaustive list.
        """
        Task = self.env['dac.work.task'].sudo()
        domain = [('state', 'not in', list(_STATES_TERMINAL))]
        if user_ids is not None:
            domain.append(('assigned_user_id', 'in', list(user_ids)))

        tasks = Task.search(
            domain,
            order='assigned_user_id asc, deadline asc, id desc',
            limit=500,
        )

        samples = {}
        counts_per_user = {}
        for task in tasks:
            uid = task.assigned_user_id.id if task.assigned_user_id else None
            n = counts_per_user.get(uid, 0)
            if n < limit:
                samples.setdefault(uid, []).append(task.id)
                counts_per_user[uid] = n + 1
        return samples

    # ══════════════════════════════════════════════════════════════════
    # Public entry points
    # ══════════════════════════════════════════════════════════════════

    @api.model
    def _get_task_progress_summary(self, now=None, user_ids=None, include_unassigned=True):
        """Return a JSON-serializable progress summary for all employees.

        :param now: reference datetime (Odoo UTC naive). Defaults to now.
        :param user_ids: list[int] — restrict to these res.users IDs.  None = all.
        :param include_unassigned: include tasks with no assigned_user_id.
               Only effective when user_ids is None.
        :return: dict — see schema documented in OUTPUT_SCHEMA section.
        """
        now = now or fields.Datetime.now()
        window_minutes = self._get_window_minutes()
        filter_ids = set(user_ids) if user_ids is not None else None

        # ── 7 aggregate queries (not N+1) ──────────────────────────
        state_counts    = self._fetch_state_counts(user_ids=filter_ids)
        overdue_counts  = self._fetch_overdue_counts(now, user_ids=filter_ids)
        due_soon_counts = self._fetch_due_soon_counts(now, window_minutes, user_ids=filter_ids)
        reminder_counts = self._fetch_reminder_due_counts(now, user_ids=filter_ids)
        next_values     = self._fetch_next_values(now, user_ids=filter_ids)
        sample_ids      = self._fetch_sample_task_ids(user_ids=filter_ids)

        # Collect every uid that appears in any metric bucket
        all_uids = (
            set(state_counts)
            | set(overdue_counts)
            | set(due_soon_counts)
            | set(next_values)
        )

        # Batch load user names (1 query, not N queries)
        user_record_ids = [uid for uid in all_uids if uid is not None]
        users_by_id = {}
        if user_record_ids:
            for u in self.env['res.users'].sudo().browse(user_record_ids):
                users_by_id[u.id] = u.name

        def _build_entry(uid, user_name):
            sc = state_counts.get(uid, {})
            metrics = {
                'total_tasks':        sum(sc.values()),
                'draft_tasks':        sc.get('draft', 0),
                'in_progress_tasks':  sc.get('in_progress', 0),
                'done_tasks':         sc.get('done', 0),
                'cancelled_tasks':    sc.get('cancelled', 0),
                'overdue_tasks':      overdue_counts.get(uid, 0),
                'due_soon_tasks':     due_soon_counts.get(uid, 0),
                'reminder_due_tasks': reminder_counts.get(uid, 0),
            }
            nv = next_values.get(uid, {})
            entry = {
                'metrics':         metrics,
                'next_deadline':   self._to_vn_iso(nv.get('next_deadline')),
                'next_remind_at':  self._to_vn_iso(nv.get('next_remind_at')),
                'sample_task_ids': sample_ids.get(uid, []),
            }
            if uid is not None:
                entry['user_id']   = uid
                entry['user_name'] = user_name or ''
            return entry

        # Sorted by user_id for deterministic output
        user_entries = [
            _build_entry(uid, users_by_id.get(uid, ''))
            for uid in sorted(uid for uid in all_uids if uid is not None)
        ]

        # Unassigned group — only when no user_ids filter is active
        unassigned_entry = None
        if include_unassigned and None in all_uids and filter_ids is None:
            unassigned_entry = _build_entry(None, None)

        def _sum(key):
            total = sum(e['metrics'][key] for e in user_entries)
            if unassigned_entry:
                total += unassigned_entry['metrics'][key]
            return total

        metric_keys = (
            'total_tasks', 'draft_tasks', 'in_progress_tasks', 'done_tasks',
            'cancelled_tasks', 'overdue_tasks', 'due_soon_tasks', 'reminder_due_tasks',
        )

        return {
            'generated_at':   self._to_vn_iso(now),
            'window_minutes': window_minutes,
            'totals':         {k: _sum(k) for k in metric_keys},
            'users':          user_entries,
            'unassigned':     unassigned_entry,
        }

    @api.model
    def _get_user_task_progress_summary(self, user, now=None):
        """Return progress summary for a single user.

        :param user: res.users record.
        :return: dict with user_id, user_name, metrics, next_deadline,
                 next_remind_at, sample_task_ids.
        """
        now = now or fields.Datetime.now()
        full = self._get_task_progress_summary(
            now=now, user_ids=[user.id], include_unassigned=False,
        )
        if full['users']:
            return full['users'][0]
        # User exists but has no tasks at all
        return {
            'user_id':   user.id,
            'user_name': user.name,
            'metrics': {k: 0 for k in (
                'total_tasks', 'draft_tasks', 'in_progress_tasks', 'done_tasks',
                'cancelled_tasks', 'overdue_tasks', 'due_soon_tasks', 'reminder_due_tasks',
            )},
            'next_deadline':   None,
            'next_remind_at':  None,
            'sample_task_ids': [],
        }
