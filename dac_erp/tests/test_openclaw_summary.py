import json
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestOpenclawSummary(TransactionCase):
    """Tests for dac.openclaw.summary.service progress aggregation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))

        group_user = cls.env.ref('base.group_user')
        cls.alice = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Alice Summary',
            'login': 'alice_summary@test.com',
            'email': 'alice_summary@test.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.bob = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Bob Summary',
            'login': 'bob_summary@test.com',
            'email': 'bob_summary@test.com',
            'groups_id': [(6, 0, [group_user.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Summary Partner'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_state_custom': 'quotation',
        })

    def _svc(self):
        return self.env['dac.openclaw.summary.service']

    def _task(self, **kwargs):
        defaults = {'order_id': self.order.id}
        defaults.update(kwargs)
        return self.env['dac.work.task'].sudo().create(defaults)

    def _alice_summary(self, now=None):
        return self._svc()._get_user_task_progress_summary(self.alice, now=now or fields.Datetime.now())

    def _bob_summary(self, now=None):
        return self._svc()._get_user_task_progress_summary(self.bob, now=now or fields.Datetime.now())

    # ── State counts ─────────────────────────────────────────────────

    def test_state_counts_draft_and_in_progress(self):
        now = fields.Datetime.now()
        self._task(name='Draft 1', assigned_user_id=self.alice.id, state='draft')
        self._task(name='Draft 2', assigned_user_id=self.alice.id, state='draft')
        self._task(name='WIP',     assigned_user_id=self.alice.id, state='in_progress')
        s = self._alice_summary(now)
        self.assertEqual(s['metrics']['draft_tasks'],       2)
        self.assertEqual(s['metrics']['in_progress_tasks'], 1)
        self.assertEqual(s['metrics']['total_tasks'],       3)

    def test_done_and_cancelled_counted(self):
        now = fields.Datetime.now()
        self._task(name='Done Task',      assigned_user_id=self.alice.id, state='done')
        self._task(name='Cancelled Task', assigned_user_id=self.alice.id, state='cancelled')
        s = self._alice_summary(now)
        self.assertGreaterEqual(s['metrics']['done_tasks'],      1)
        self.assertGreaterEqual(s['metrics']['cancelled_tasks'], 1)

    # ── Overdue ───────────────────────────────────────────────────────

    def test_overdue_task_counted(self):
        now = fields.Datetime.now()
        self._task(
            name='Overdue',
            assigned_user_id=self.alice.id,
            state='in_progress',
            deadline=now - timedelta(hours=2),
        )
        s = self._alice_summary(now)
        self.assertGreaterEqual(s['metrics']['overdue_tasks'], 1)

    def test_done_overdue_not_counted(self):
        """Completed task with past deadline must NOT appear in overdue."""
        now = fields.Datetime.now()
        self._task(
            name='Done Overdue',
            assigned_user_id=self.alice.id,
            state='done',
            deadline=now - timedelta(hours=5),
        )
        s = self._alice_summary(now)
        # done task must not inflate overdue count
        self.assertEqual(s['metrics']['done_tasks'], 1)
        self.assertEqual(s['metrics']['overdue_tasks'], 0)

    # ── Due soon ─────────────────────────────────────────────────────

    def test_due_soon_task_counted(self):
        """Task with deadline 60 min away is within default 120-min window."""
        now = fields.Datetime.now()
        self._task(
            name='Due Soon',
            assigned_user_id=self.alice.id,
            state='in_progress',
            deadline=now + timedelta(minutes=60),
        )
        s = self._alice_summary(now)
        self.assertGreaterEqual(s['metrics']['due_soon_tasks'], 1)

    def test_due_soon_excludes_overdue(self):
        """Overdue task (deadline < now) must NOT appear in due_soon."""
        now = fields.Datetime.now()
        self._task(
            name='Overdue Not Soon',
            assigned_user_id=self.alice.id,
            state='in_progress',
            deadline=now - timedelta(minutes=30),
        )
        s = self._alice_summary(now)
        self.assertEqual(s['metrics']['due_soon_tasks'], 0)

    def test_due_soon_excludes_far_future(self):
        """Task with deadline 5 hours away is outside default 120-min window."""
        now = fields.Datetime.now()
        self._task(
            name='Far Future',
            assigned_user_id=self.alice.id,
            state='draft',
            deadline=now + timedelta(hours=5),
        )
        s = self._alice_summary(now)
        self.assertEqual(s['metrics']['due_soon_tasks'], 0)

    # ── Reminder due ─────────────────────────────────────────────────

    def test_reminder_due_for_passed_remind_at(self):
        """Task with remind_at in the past (within 48h, no previous reminder) is counted."""
        now = fields.Datetime.now()
        self._task(
            name='Remind Due',
            assigned_user_id=self.alice.id,
            state='in_progress',
            remind_at=now - timedelta(hours=1),
        )
        s = self._alice_summary(now)
        self.assertGreaterEqual(s['metrics']['reminder_due_tasks'], 1)

    def test_reminder_due_skips_within_cooldown(self):
        """Task reminded 20 min ago (within 60-min cooldown) must NOT be counted."""
        now = fields.Datetime.now()
        self._task(
            name='Cooldown Reminder',
            assigned_user_id=self.alice.id,
            state='in_progress',
            remind_at=now - timedelta(hours=1),
            x_openclaw_last_reminder_at=now - timedelta(minutes=20),
        )
        s = self._alice_summary(now)
        self.assertEqual(s['metrics']['reminder_due_tasks'], 0)

    # ── next_deadline / next_remind_at ───────────────────────────────

    def test_next_deadline_is_earliest_future(self):
        now = fields.Datetime.now()
        sooner = now + timedelta(hours=2)
        later  = now + timedelta(hours=6)
        self._task(name='Later DL',  assigned_user_id=self.alice.id, state='draft', deadline=later)
        self._task(name='Sooner DL', assigned_user_id=self.alice.id, state='draft', deadline=sooner)
        s = self._alice_summary(now)
        self.assertIsNotNone(s['next_deadline'])
        # ISO string must represent sooner deadline (smaller value)
        self.assertIn('+07:00', s['next_deadline'])

    def test_next_remind_at_is_earliest_future(self):
        now = fields.Datetime.now()
        ra1 = now + timedelta(hours=1)
        ra2 = now + timedelta(hours=4)
        self._task(name='Remind Far',  assigned_user_id=self.alice.id, state='draft', remind_at=ra2)
        self._task(name='Remind Near', assigned_user_id=self.alice.id, state='draft', remind_at=ra1)
        s = self._alice_summary(now)
        self.assertIsNotNone(s['next_remind_at'])

    def test_next_values_null_when_no_future_dates(self):
        """User with only tasks that have no deadline/remind_at → both None."""
        now = fields.Datetime.now()
        self._task(name='No DL', assigned_user_id=self.alice.id, state='draft')
        s = self._alice_summary(now)
        self.assertIsNone(s['next_deadline'])
        self.assertIsNone(s['next_remind_at'])

    # ── User with no tasks ───────────────────────────────────────────

    def test_user_with_no_tasks_returns_zeros(self):
        now = fields.Datetime.now()
        s = self._bob_summary(now)
        self.assertEqual(s['user_id'],   self.bob.id)
        self.assertEqual(s['user_name'], 'Bob Summary')
        for key in ('total_tasks', 'overdue_tasks', 'due_soon_tasks', 'reminder_due_tasks'):
            self.assertEqual(s['metrics'][key], 0, f"{key} should be 0")
        self.assertIsNone(s['next_deadline'])
        self.assertIsNone(s['next_remind_at'])
        self.assertEqual(s['sample_task_ids'], [])

    # ── Unassigned tasks ─────────────────────────────────────────────

    def test_unassigned_tasks_in_summary(self):
        """Tasks with no assigned_user_id appear under 'unassigned' key."""
        now = fields.Datetime.now()
        self._task(name='Unassigned Draft', state='draft')  # no assigned_user_id

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=None, include_unassigned=True,
        )
        self.assertIsNotNone(summary['unassigned'])
        self.assertGreaterEqual(summary['unassigned']['metrics']['total_tasks'], 1)

    def test_unassigned_excluded_when_flag_false(self):
        now = fields.Datetime.now()
        self._task(name='Unassigned 2', state='draft')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=None, include_unassigned=False,
        )
        self.assertIsNone(summary['unassigned'])

    def test_unassigned_excluded_when_user_ids_filter_set(self):
        """When user_ids is specified, unassigned group is always excluded."""
        now = fields.Datetime.now()
        self._task(name='Unassigned 3', state='draft')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=True,
        )
        self.assertIsNone(summary['unassigned'])

    # ── Filter by user_ids ───────────────────────────────────────────

    def test_filter_by_user_ids_excludes_others(self):
        now = fields.Datetime.now()
        self._task(name='Alice Filtered', assigned_user_id=self.alice.id, state='draft')
        self._task(name='Bob Filtered',   assigned_user_id=self.bob.id,   state='draft')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=False,
        )
        ids_in_result = [u['user_id'] for u in summary['users']]
        self.assertIn(self.alice.id,    ids_in_result)
        self.assertNotIn(self.bob.id,   ids_in_result)

    def test_filter_two_users(self):
        now = fields.Datetime.now()
        self._task(name='Alice F', assigned_user_id=self.alice.id, state='in_progress')
        self._task(name='Bob F',   assigned_user_id=self.bob.id,   state='draft')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id, self.bob.id], include_unassigned=False,
        )
        ids_in_result = {u['user_id'] for u in summary['users']}
        self.assertIn(self.alice.id, ids_in_result)
        self.assertIn(self.bob.id,   ids_in_result)

    # ── Totals ────────────────────────────────────────────────────────

    def test_totals_equal_sum_of_users(self):
        now = fields.Datetime.now()
        self._task(name='Total Alice', assigned_user_id=self.alice.id, state='draft')
        self._task(name='Total Bob',   assigned_user_id=self.bob.id,   state='in_progress')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id, self.bob.id], include_unassigned=False,
        )
        for key in ('total_tasks', 'draft_tasks', 'in_progress_tasks', 'overdue_tasks'):
            users_sum = sum(u['metrics'][key] for u in summary['users'])
            self.assertEqual(summary['totals'][key], users_sum,
                             f"totals.{key} should equal sum of per-user values")

    # ── Output schema ─────────────────────────────────────────────────

    def test_top_level_keys_present(self):
        now = fields.Datetime.now()
        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=False,
        )
        for key in ('generated_at', 'window_minutes', 'totals', 'users', 'unassigned'):
            self.assertIn(key, summary, f"Top-level key '{key}' must be present")

    def test_user_entry_keys_present(self):
        now = fields.Datetime.now()
        self._task(name='Schema Task', assigned_user_id=self.alice.id, state='draft')
        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=False,
        )
        self.assertEqual(len(summary['users']), 1)
        entry = summary['users'][0]
        for key in ('user_id', 'user_name', 'metrics', 'next_deadline', 'next_remind_at', 'sample_task_ids'):
            self.assertIn(key, entry, f"User entry key '{key}' must be present")
        for mkey in ('total_tasks', 'draft_tasks', 'in_progress_tasks', 'done_tasks',
                     'cancelled_tasks', 'overdue_tasks', 'due_soon_tasks', 'reminder_due_tasks'):
            self.assertIn(mkey, entry['metrics'], f"Metric key '{mkey}' must be present")

    # ── JSON serialization ────────────────────────────────────────────

    def test_output_is_json_serializable_no_tasks(self):
        now = fields.Datetime.now()
        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.bob.id], include_unassigned=False,
        )
        serialized = json.dumps(summary)
        self.assertIsInstance(serialized, str)
        restored = json.loads(serialized)
        self.assertEqual(restored['totals']['total_tasks'], 0)

    def test_output_is_json_serializable_with_tasks(self):
        now = fields.Datetime.now()
        self._task(
            name='JSON Task',
            assigned_user_id=self.alice.id,
            state='in_progress',
            deadline=now + timedelta(hours=2),
            remind_at=now + timedelta(hours=1),
        )
        self._task(
            name='JSON Overdue',
            assigned_user_id=self.alice.id,
            state='draft',
            deadline=now - timedelta(hours=1),
        )
        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=False,
        )
        # Must not raise
        serialized = json.dumps(summary)
        restored = json.loads(serialized)
        alice_entry = next(u for u in restored['users'] if u['user_id'] == self.alice.id)
        self.assertEqual(alice_entry['metrics']['total_tasks'], 2)
        self.assertIsNotNone(alice_entry['next_deadline'])
        # ISO 8601 string with +07:00
        self.assertIn('+07:00', alice_entry['next_deadline'])

    # ── Sample task IDs ───────────────────────────────────────────────

    def test_sample_task_ids_are_integers(self):
        now = fields.Datetime.now()
        for i in range(4):
            self._task(name=f'Sample {i}', assigned_user_id=self.alice.id, state='draft')
        s = self._alice_summary(now)
        self.assertGreater(len(s['sample_task_ids']), 0)
        for tid in s['sample_task_ids']:
            self.assertIsInstance(tid, int)

    def test_sample_task_ids_capped_at_limit(self):
        now = fields.Datetime.now()
        for i in range(10):
            self._task(name=f'Cap Sample {i}', assigned_user_id=self.alice.id, state='draft')
        s = self._alice_summary(now)
        self.assertLessEqual(len(s['sample_task_ids']), 5)

    # ── generated_at format ───────────────────────────────────────────

    def test_generated_at_is_vn_timezone(self):
        now = fields.Datetime.now()
        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id], include_unassigned=False,
        )
        self.assertIsNotNone(summary['generated_at'])
        self.assertIn('+07:00', summary['generated_at'])

    # ── Multi-user consistency ────────────────────────────────────────

    def test_multi_user_tasks_isolated(self):
        """Each user's metrics only count their own tasks."""
        now = fields.Datetime.now()
        self._task(name='A1', assigned_user_id=self.alice.id, state='draft')
        self._task(name='A2', assigned_user_id=self.alice.id, state='draft')
        self._task(name='B1', assigned_user_id=self.bob.id,   state='in_progress')

        summary = self._svc()._get_task_progress_summary(
            now=now, user_ids=[self.alice.id, self.bob.id], include_unassigned=False,
        )
        users_by_id = {u['user_id']: u for u in summary['users']}
        alice = users_by_id[self.alice.id]
        bob   = users_by_id[self.bob.id]

        self.assertEqual(alice['metrics']['draft_tasks'],       2)
        self.assertEqual(alice['metrics']['in_progress_tasks'], 0)
        self.assertEqual(bob['metrics']['in_progress_tasks'],   1)
        self.assertEqual(bob['metrics']['draft_tasks'],         0)
