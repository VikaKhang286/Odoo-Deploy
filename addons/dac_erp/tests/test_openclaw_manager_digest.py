"""Tests for dac.openclaw.manager.digest.service (Phần 5).

Covers:
  - _get_manager_scope_users: manager vs employee/admin roles
  - _get_digest_event_id: AM/PM period, date boundary
  - _get_manager_task_summary: delegates to summary service
  - _user_urgency_score: ranking formula
  - _build_manager_digest_message: message structure, top-N, empty case
  - _send_manager_digest: anti-spam, no_scope, skipped, sent/failed paths
  - cron_send_openclaw_manager_digest: loops all managers, stats logging
  - Config helpers: enabled flag, top_n, skip_if_empty
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestManagerDigestScopeUsers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u1 = cls.env['res.users'].create({
            'name': 'NV Anh',
            'login': 'nv_anh_digest@test.local',
            'email': 'nv_anh_digest@test.local',
        })
        cls.u2 = cls.env['res.users'].create({
            'name': 'NV Binh',
            'login': 'nv_binh_digest@test.local',
            'email': 'nv_binh_digest@test.local',
        })
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Manager Digest',
            'login': 'mgr_digest@test.local',
            'email': 'mgr_digest@test.local',
        })
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _make_mapping(self, user, role='manager', target=None, digest_enabled=True, scope_users=None):
        import random
        t = target or 'test-target-%d' % random.randint(1000000, 9999999)
        vals = {
            'user_id': user.id,
            'channel': 'telegram',
            'target': t,
            'role': role,
            'active': True,
            'digest_enabled': digest_enabled,
        }
        mapping = self.env['dac.openclaw.user.mapping'].create(vals)
        if scope_users:
            mapping.manager_user_ids = [(6, 0, [u.id for u in scope_users])]
        return mapping

    def test_scope_users_manager_with_users(self):
        mapping = self._make_mapping(self.manager_user, scope_users=[self.u1, self.u2])
        result = self.svc._get_manager_scope_users(mapping)
        self.assertIn(self.u1.id, result)
        self.assertIn(self.u2.id, result)
        self.assertNotIn(self.manager_user.id, result)

    def test_scope_users_manager_empty(self):
        mapping = self._make_mapping(self.manager_user)
        result = self.svc._get_manager_scope_users(mapping)
        self.assertEqual(result, [])

    def test_scope_users_employee_returns_empty(self):
        mapping = self._make_mapping(self.u1, role='employee')
        result = self.svc._get_manager_scope_users(mapping)
        self.assertEqual(result, [])

    def test_scope_users_admin_returns_empty(self):
        mapping = self._make_mapping(self.manager_user, role='admin')
        result = self.svc._get_manager_scope_users(mapping)
        self.assertEqual(result, [])


@tagged('post_install', '-at_install')
class TestManagerDigestEventId(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _utc(self, *args):
        return datetime(*args)

    def test_event_id_am(self):
        # 05:00 UTC = 12:00 VN → still AM (12:00 is pm boundary)
        # 01:00 UTC = 08:00 VN → AM
        now = self._utc(2026, 5, 15, 1, 0, 0)
        eid = self.svc._get_digest_event_id(42, now)
        self.assertEqual(eid, 'manager_digest-42-20260515-am')

    def test_event_id_pm(self):
        # 06:00 UTC = 13:00 VN → PM
        now = self._utc(2026, 5, 15, 6, 0, 0)
        eid = self.svc._get_digest_event_id(42, now)
        self.assertEqual(eid, 'manager_digest-42-20260515-pm')

    def test_event_id_midnight_vn_is_am(self):
        # 17:00 UTC previous day = 00:00 VN next day → AM
        now = self._utc(2026, 5, 14, 17, 0, 0)
        eid = self.svc._get_digest_event_id(7, now)
        self.assertEqual(eid, 'manager_digest-7-20260515-am')

    def test_event_id_different_mappings_differ(self):
        now = self._utc(2026, 5, 15, 1, 0, 0)
        eid1 = self.svc._get_digest_event_id(1, now)
        eid2 = self.svc._get_digest_event_id(2, now)
        self.assertNotEqual(eid1, eid2)

    def test_event_id_same_period_same_id(self):
        now1 = self._utc(2026, 5, 15, 2, 0, 0)
        now2 = self._utc(2026, 5, 15, 3, 30, 0)
        eid1 = self.svc._get_digest_event_id(5, now1)
        eid2 = self.svc._get_digest_event_id(5, now2)
        self.assertEqual(eid1, eid2)

    def test_event_id_am_pm_differ(self):
        now_am = self._utc(2026, 5, 15, 1, 0, 0)   # 08:00 VN
        now_pm = self._utc(2026, 5, 15, 7, 0, 0)   # 14:00 VN
        eid_am = self.svc._get_digest_event_id(5, now_am)
        eid_pm = self.svc._get_digest_event_id(5, now_pm)
        self.assertNotEqual(eid_am, eid_pm)


@tagged('post_install', '-at_install')
class TestManagerDigestUrgencyScore(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _entry(self, overdue=0, due_soon=0, reminder_due=0, in_progress=0):
        return {'metrics': {
            'overdue_tasks': overdue,
            'due_soon_tasks': due_soon,
            'reminder_due_tasks': reminder_due,
            'in_progress_tasks': in_progress,
        }}

    def test_overdue_dominates(self):
        high = self._entry(overdue=1)
        low = self._entry(due_soon=5, in_progress=10)
        self.assertGreater(
            self.svc._user_urgency_score(high),
            self.svc._user_urgency_score(low),
        )

    def test_due_soon_beats_reminder_due(self):
        a = self._entry(due_soon=1)
        b = self._entry(reminder_due=1)
        self.assertGreater(
            self.svc._user_urgency_score(a),
            self.svc._user_urgency_score(b),
        )

    def test_zero_score(self):
        self.assertEqual(self.svc._user_urgency_score(self._entry()), 0)

    def test_score_formula(self):
        entry = self._entry(overdue=2, due_soon=3, reminder_due=1, in_progress=4)
        expected = 2 * 100 + 3 * 10 + 1 * 5 + 4
        self.assertEqual(self.svc._user_urgency_score(entry), expected)


@tagged('post_install', '-at_install')
class TestManagerDigestMessage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Manager Msg',
            'login': 'mgr_msg@test.local',
            'email': 'mgr_msg@test.local',
        })
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _make_mapping(self):
        import random
        return self.env['dac.openclaw.user.mapping'].create({
            'user_id': self.manager_user.id,
            'channel': 'telegram',
            'target': 'tgt-msg-%d' % __import__('random').randint(1000, 9999),
            'role': 'manager',
            'active': True,
        })

    def _summary(self, users=None, totals=None):
        default_totals = {
            'total_tasks': 5, 'in_progress_tasks': 2,
            'overdue_tasks': 1, 'due_soon_tasks': 1,
            'draft_tasks': 1, 'done_tasks': 0,
            'cancelled_tasks': 0, 'reminder_due_tasks': 0,
        }
        return {
            'generated_at': '2026-05-15T07:30:00+07:00',
            'window_minutes': 120,
            'totals': totals or default_totals,
            'users': users or [],
            'unassigned': None,
        }

    def test_message_contains_manager_name(self):
        mapping = self._make_mapping()
        msg = self.svc._build_manager_digest_message(self._summary(), mapping)
        self.assertIn('Manager Msg', msg)

    def test_message_contains_time_label(self):
        mapping = self._make_mapping()
        msg = self.svc._build_manager_digest_message(self._summary(), mapping)
        self.assertIn('07:30', msg)
        self.assertIn('15/05/2026', msg)

    def test_message_contains_totals(self):
        mapping = self._make_mapping()
        msg = self.svc._build_manager_digest_message(self._summary(), mapping)
        self.assertIn('5 task', msg)

    def test_message_top_n_users(self):
        mapping = self._make_mapping()
        users = [
            {'user_id': 1, 'user_name': 'NV A', 'metrics': {
                'total_tasks': 3, 'overdue_tasks': 2, 'due_soon_tasks': 0,
                'in_progress_tasks': 1, 'draft_tasks': 0, 'done_tasks': 0,
                'cancelled_tasks': 0, 'reminder_due_tasks': 0,
            }},
            {'user_id': 2, 'user_name': 'NV B', 'metrics': {
                'total_tasks': 2, 'overdue_tasks': 0, 'due_soon_tasks': 1,
                'in_progress_tasks': 1, 'draft_tasks': 0, 'done_tasks': 0,
                'cancelled_tasks': 0, 'reminder_due_tasks': 0,
            }},
            {'user_id': 3, 'user_name': 'NV C', 'metrics': {
                'total_tasks': 1, 'overdue_tasks': 0, 'due_soon_tasks': 0,
                'in_progress_tasks': 0, 'draft_tasks': 1, 'done_tasks': 0,
                'cancelled_tasks': 0, 'reminder_due_tasks': 0,
            }},
            {'user_id': 4, 'user_name': 'NV D', 'metrics': {
                'total_tasks': 1, 'overdue_tasks': 0, 'due_soon_tasks': 0,
                'in_progress_tasks': 0, 'draft_tasks': 1, 'done_tasks': 0,
                'cancelled_tasks': 0, 'reminder_due_tasks': 0,
            }},
        ]
        msg = self.svc._build_manager_digest_message(self._summary(users=users), mapping)
        # Top 3 default: NV A (score 200), NV B (score 11), NV C or NV D (score 0)
        self.assertIn('NV A', msg)
        self.assertIn('NV B', msg)
        # NV D should NOT appear (beyond top-3)
        lines_with_nv = [l for l in msg.split('\n') if l.strip().startswith(('1.', '2.', '3.', '4.'))]
        self.assertLessEqual(len(lines_with_nv), 3)

    def test_message_empty_users(self):
        mapping = self._make_mapping()
        msg = self.svc._build_manager_digest_message(self._summary(users=[]), mapping)
        self.assertIn('khong co du lieu', msg)

    def test_message_overdue_status_shown(self):
        mapping = self._make_mapping()
        users = [{'user_id': 1, 'user_name': 'NV X', 'metrics': {
            'total_tasks': 2, 'overdue_tasks': 1, 'due_soon_tasks': 0,
            'in_progress_tasks': 0, 'draft_tasks': 1, 'done_tasks': 0,
            'cancelled_tasks': 0, 'reminder_due_tasks': 0,
        }}]
        msg = self.svc._build_manager_digest_message(self._summary(users=users), mapping)
        self.assertIn('qua han', msg)


@tagged('post_install', '-at_install')
class TestManagerDigestSend(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u1 = cls.env['res.users'].create({
            'name': 'NV Send1',
            'login': 'nv_send1@test.local',
            'email': 'nv_send1@test.local',
        })
        cls.u2 = cls.env['res.users'].create({
            'name': 'NV Send2',
            'login': 'nv_send2@test.local',
            'email': 'nv_send2@test.local',
        })
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Manager Send',
            'login': 'mgr_send@test.local',
            'email': 'mgr_send@test.local',
        })
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _make_mapping(self, scope_users=None, digest_enabled=True):
        import random
        mapping = self.env['dac.openclaw.user.mapping'].create({
            'user_id': self.manager_user.id,
            'channel': 'telegram',
            'target': 'tgt-send-%d' % random.randint(1000000, 9999999),
            'role': 'manager',
            'active': True,
            'digest_enabled': digest_enabled,
        })
        if scope_users:
            mapping.manager_user_ids = [(6, 0, [u.id for u in scope_users])]
        return mapping

    def _make_task(self, user, state='in_progress', deadline=None):
        task = self.env['dac.work.task'].create({
            'name': 'Digest Test Task',
            'assigned_user_id': user.id,
            'state': state,
            'is_personal_reminder': True,  # bypass order/conv constraint in tests
        })
        if deadline:
            task.deadline = deadline
        return task

    def _now(self):
        from odoo import fields
        return fields.Datetime.now()

    def test_send_returns_no_scope_when_no_scope_users(self):
        mapping = self._make_mapping(scope_users=[])
        result = self.svc._send_manager_digest(mapping, now=self._now())
        self.assertEqual(result, 'no_scope')

    def test_send_returns_skipped_when_digest_disabled(self):
        mapping = self._make_mapping(scope_users=[self.u1], digest_enabled=False)
        result = self.svc._send_manager_digest(mapping, now=self._now())
        self.assertEqual(result, 'skipped')

    def test_send_returns_skipped_when_no_tasks(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        now = self._now()
        with patch.object(
            type(self.svc), '_get_digest_skip_if_empty', return_value=True
        ):
            result = self.svc._send_manager_digest(mapping, now=now)
        self.assertEqual(result, 'skipped')

    def test_send_returns_already_sent_when_log_exists(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        self._make_task(self.u1)
        now = self._now()
        event_id = self.svc._get_digest_event_id(mapping.id, now)
        # Pre-create the log entry
        self.env['dac.openclaw.notification.log'].create({
            'event_id': event_id,
            'event_type': 'manager_digest',
            'status': 'sent',
        })
        result = self.svc._send_manager_digest(mapping, now=now)
        self.assertEqual(result, 'already_sent')

    def test_send_returns_failed_when_no_base_url(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        self._make_task(self.u1)
        now = self._now()
        # Ensure no base_url configured
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_base_url', ''
        )
        result = self.svc._send_manager_digest(mapping, now=now)
        self.assertEqual(result, 'failed')

    def test_send_calls_webhook_with_correct_event_type(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        self._make_task(self.u1)
        now = self._now()
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_base_url', 'http://mock-openclaw'
        )
        captured = []

        def mock_post(url, data=None, headers=None, timeout=None):
            captured.append({'url': url, 'data': data})
            import unittest.mock as mock
            r = mock.MagicMock()
            r.status_code = 200
            r.text = 'ok'
            r.raise_for_status = lambda: None
            return r

        with patch('requests.post', side_effect=mock_post):
            result = self.svc._send_manager_digest(mapping, now=now)

        self.assertEqual(result, 'sent')
        self.assertEqual(len(captured), 1)
        self.assertIn('/hooks/odoo-manager-digest', captured[0]['url'])

    def test_send_creates_log_entry(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        self._make_task(self.u1)
        now = self._now()
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_base_url', 'http://mock-openclaw'
        )

        import unittest.mock as mock

        def mock_post(url, data=None, headers=None, timeout=None):
            r = mock.MagicMock()
            r.status_code = 200
            r.text = 'ok'
            r.raise_for_status = lambda: None
            return r

        event_id = self.svc._get_digest_event_id(mapping.id, now)
        with patch('requests.post', side_effect=mock_post):
            self.svc._send_manager_digest(mapping, now=now)

        log = self.env['dac.openclaw.notification.log'].search(
            [('event_id', '=', event_id)]
        )
        self.assertEqual(len(log), 1)
        self.assertEqual(log.event_type, 'manager_digest')
        self.assertEqual(log.status, 'sent')

    def test_send_no_duplicate_on_second_call(self):
        mapping = self._make_mapping(scope_users=[self.u1])
        self._make_task(self.u1)
        now = self._now()
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_base_url', 'http://mock-openclaw'
        )

        import unittest.mock as mock

        def mock_post(url, data=None, headers=None, timeout=None):
            r = mock.MagicMock()
            r.status_code = 200
            r.text = 'ok'
            r.raise_for_status = lambda: None
            return r

        with patch('requests.post', side_effect=mock_post):
            r1 = self.svc._send_manager_digest(mapping, now=now)
        r2 = self.svc._send_manager_digest(mapping, now=now)
        self.assertEqual(r1, 'sent')
        self.assertEqual(r2, 'already_sent')


@tagged('post_install', '-at_install')
class TestManagerDigestCron(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.u1 = cls.env['res.users'].create({
            'name': 'NV Cron1',
            'login': 'nv_cron1@test.local',
            'email': 'nv_cron1@test.local',
        })
        cls.manager_a = cls.env['res.users'].create({
            'name': 'Manager A Cron',
            'login': 'mgr_a_cron@test.local',
            'email': 'mgr_a_cron@test.local',
        })
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def _make_manager_mapping(self, user, scope_users=None, digest_enabled=True):
        import random
        mapping = self.env['dac.openclaw.user.mapping'].create({
            'user_id': user.id,
            'channel': 'telegram',
            'target': 'tgt-cron-%d' % random.randint(1000000, 9999999),
            'role': 'manager',
            'active': True,
            'digest_enabled': digest_enabled,
        })
        if scope_users:
            mapping.manager_user_ids = [(6, 0, [u.id for u in scope_users])]
        return mapping

    def test_cron_skipped_when_feature_disabled(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_enabled', 'False'
        )
        # Should not raise; just log and return
        self.svc.cron_send_openclaw_manager_digest()

    def test_cron_processes_active_manager_mappings(self):
        self._make_manager_mapping(self.manager_a, scope_users=[self.u1])
        self.env['dac.work.task'].create({
            'name': 'Cron Task',
            'assigned_user_id': self.u1.id,
            'state': 'in_progress',
            'is_personal_reminder': True,
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_enabled', 'True'
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_base_url', ''
        )
        # With no base_url, each mapping should fail (not raise)
        self.svc.cron_send_openclaw_manager_digest()

    def test_cron_does_not_raise_on_exception_per_mapping(self):
        self._make_manager_mapping(self.manager_a, scope_users=[self.u1])
        self.env['dac.work.task'].create({
            'name': 'Cron Error Task',
            'assigned_user_id': self.u1.id,
            'state': 'in_progress',
            'is_personal_reminder': True,
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_enabled', 'True'
        )

        def exploding_send(*args, **kwargs):
            raise RuntimeError('simulated crash')

        with patch.object(type(self.svc), '_send_manager_digest', side_effect=exploding_send):
            # Must not propagate — cron must swallow exceptions
            self.svc.cron_send_openclaw_manager_digest()


@tagged('post_install', '-at_install')
class TestManagerDigestConfig(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env['dac.openclaw.manager.digest.service']

    def test_digest_top_n_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_top_n', ''
        )
        self.assertEqual(self.svc._get_digest_top_n(), 3)

    def test_digest_top_n_custom(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_top_n', '5'
        )
        self.assertEqual(self.svc._get_digest_top_n(), 5)

    def test_digest_enabled_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_enabled', ''
        )
        self.assertTrue(self.svc._get_digest_enabled())

    def test_digest_enabled_false(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_enabled', 'False'
        )
        self.assertFalse(self.svc._get_digest_enabled())

    def test_digest_skip_if_empty_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_skip_if_empty', ''
        )
        self.assertTrue(self.svc._get_digest_skip_if_empty())

    def test_digest_skip_if_empty_false(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'dac_erp.openclaw_manager_digest_skip_if_empty', '0'
        )
        self.assertFalse(self.svc._get_digest_skip_if_empty())
