import logging
from datetime import datetime, timedelta, time
import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class KpiSaleDaily(models.Model):
    _name = 'kpi.sale.daily'
    _description = 'Daily Sales KPI Report'
    _order = 'date desc, user_id'
    _rec_name = 'user_id'

    date = fields.Date(string="Date", required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', string="Staff", required=True, readonly=True, ondelete='cascade', index=True)
    
    total_messages = fields.Integer(string="Total Messages", readonly=True, help="Total messages sent by this staff member on this day.")
    messages_after_hours = fields.Integer(string="Messages After Hours", readonly=True, help="Messages sent outside business hours (8:30-18:00).")
    unreplied_conversations_count = fields.Integer(string="Unreplied Conversations (EOD)", readonly=True, help="Conversations where the last message of the day was from the customer, and this staff member was involved.")
    
    avg_response_time = fields.Float(string="Avg. Response Time (Total, Mins)", readonly=True, digits=(16, 2), help="Overall average response time in minutes.")
    avg_response_time_bh = fields.Float(string="Avg. Response Time (Business Hours, Mins)", readonly=True, digits=(16, 2), help="Average response time in minutes, only for responses made during business hours.")

    avg_response_time_string = fields.Char(string="Avg. Response Time (Formatted)", store=True, readonly=True, help="Formatted average response time string.")
    avg_response_time_bh_string = fields.Char(string="Avg. Response Time (Business Hours, Formatted)", store=True, readonly=True, help="Formatted average response time during business hours string.")


    company_id = fields.Many2one('res.company', string='Company', readonly=True, default=lambda self: self.env.company)

    def _calculate_response_times(self, user, target_date):
        """
        Calculate response times for a specific user on a given date.
        A response is a message from the user that directly follows a message from a customer.
        """
        Message = self.env['page.fm.message']
        
        # Find all conversations the user participated in on the target date
        start_dt = datetime.combine(target_date, time.min)
        end_dt = datetime.combine(target_date, time.max)
        
        user_messages_today = Message.search([
            ('staff_name_fm', '=', user.name),
            ('inserted_at_fm', '>=', start_dt),
            ('inserted_at_fm', '<=', end_dt)
        ])
        
        if not user_messages_today:
            return [], []

        involved_conversation_ids = user_messages_today.mapped('conversation_id').ids
        all_conv_messages = Message.search([('conversation_id', 'in', involved_conversation_ids)], order='inserted_at_fm asc')

        response_times_total = []
        response_times_bh = []
        
        # Odoo's timezone or a default, change if needed
        local_tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')
        bh_start = time(8, 30)
        bh_end = time(18, 0)

        # Group messages by conversation
        convo_messages_map = {}
        for msg in all_conv_messages:
            convo_messages_map.setdefault(msg.conversation_id.id, []).append(msg)

        for conv_id in involved_conversation_ids:
            messages = convo_messages_map.get(conv_id, [])
            for i, msg in enumerate(messages):
                if i > 0 and msg.staff_name_fm == user.name:
                    prev_msg = messages[i-1]
                    # Check if the previous message is from a customer
                    if not prev_msg.staff_name_fm and prev_msg.sender_name_fm:
                        # This is a response. Calculate the time difference.
                        response_time_delta = msg.inserted_at_fm - prev_msg.inserted_at_fm
                        response_times_total.append(response_time_delta.total_seconds())

                        # Check if response was within business hours
                        response_dt_local = pytz.utc.localize(msg.inserted_at_fm).astimezone(local_tz)
                        if bh_start <= response_dt_local.time() <= bh_end and response_dt_local.weekday() < 5: # Mon-Fri
                            response_times_bh.append(response_time_delta.total_seconds())
                            
        return response_times_total, response_times_bh

    def format_duration(self,seconds):
        seconds = int(seconds)
        days, seconds = divmod(seconds, 86400)       # 86400 = 60*60*24
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        
        parts = []
        if days:
            parts.append(f"{days} ngày")
        if hours:
            parts.append(f"{hours} giờ")
        if minutes:
            parts.append(f"{minutes} phút")
        if seconds or not parts:
            parts.append(f"{seconds} giây")
        
        return ' '.join(parts)


    @api.model
    def _cron_calculate_daily_kpi(self, calculation_date=None):
        """
        Scheduled action to calculate KPIs for a specific day.
        If calculation_date is None, it defaults to the previous day.
        """
        target_date = calculation_date or (fields.Date.context_today(self) - timedelta(days=1))
        #_logger.info(f"Starting daily KPI calculation for {target_date}")

        Message = self.env['page.fm.message']
        local_tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')
        bh_start_hour = 8.5  # 8:30 AM
        bh_end_hour = 18.0   # 6:00 PM

        # Get all messages from the target date
        start_dt = datetime.combine(target_date, time.min)
        end_dt = datetime.combine(target_date, time.max)
        
        messages_on_date = Message.search([
            ('inserted_at_fm', '>=', start_dt),
            ('inserted_at_fm', '<=', end_dt),
            ('staff_name_fm', '!=', False)
        ])
        
        staff_names = messages_on_date.mapped('staff_name_fm')
        if not staff_names:
            #_logger.info(f"No staff messages found for {target_date}. Skipping KPI calculation.")
            return

        users = self.env['res.users'].search([('name', 'in', list(set(staff_names)))])
        user_map = {user.name: user for user in users}

        # _logger.info(f"Calculating KPIs on {target_date}")
        for user_name in staff_names:
            user = user_map.get(user_name)
            if not user:
                _logger.warning(f"Could not find a user with name '{user_name}'. Skipping.")
                continue

            
            # 1. Total Messages and Messages After Hours
            user_messages = messages_on_date.filtered(lambda m: m.staff_name_fm == user.name)
            total_msg_count = len(user_messages)
            
            after_hours_count = 0
            for msg in user_messages:
                msg_time_local = pytz.utc.localize(msg.inserted_at_fm).astimezone(local_tz)
                hour = msg_time_local.hour + msg_time_local.minute / 60.0
                if not (bh_start_hour <= hour < bh_end_hour and msg_time_local.weekday() < 5):
                    after_hours_count += 1

            # 2. Average Response Times
            resp_total_secs, resp_bh_secs = self._calculate_response_times(user, target_date)
            avg_resp_total_mins = (sum(resp_total_secs) / len(resp_total_secs) / 60) if resp_total_secs else 0.0
            avg_resp_bh_mins = (sum(resp_bh_secs) / len(resp_bh_secs) / 60) if resp_bh_secs else 0.0
            avg_response_time_string = self.format_duration(avg_resp_total_mins * 60)  # Convert to seconds for formatting
            avg_response_time_bh_string = self.format_duration(avg_resp_bh_mins * 60)  # Convert to seconds for formatting

            # 3. Unreplied conversations
            involved_conv_ids = user_messages.mapped('conversation_id').ids
            unreplied_count = 0
            for conv_id in involved_conv_ids:
                # Find the last message of the day for this conversation
                last_msg_of_day = Message.search([
                    ('conversation_id', '=', conv_id),
                    ('inserted_at_fm', '<=', end_dt)
                ], order='inserted_at_fm desc', limit=1)

                # If the last message is from a customer, it's unreplied overnight
                if last_msg_of_day and not last_msg_of_day.staff_name_fm:
                    unreplied_count += 1
            
            # Create or update the KPI record
            kpi_record = self.search([('user_id', '=', user.id), ('date', '=', target_date)], limit=1)
            vals = {
                'total_messages': total_msg_count,
                'messages_after_hours': after_hours_count,
                'unreplied_conversations_count': unreplied_count,
                'avg_response_time': avg_resp_total_mins,
                'avg_response_time_bh': avg_resp_bh_mins,
                'avg_response_time_string': avg_response_time_string,
                'avg_response_time_bh_string': avg_response_time_bh_string,
            }
            if kpi_record:
                kpi_record.write(vals)
                # _logger.info(f"Updated KPI record for {user.name} on {target_date}")
            else:
                vals.update({'user_id': user.id, 'date': target_date})
                self.create(vals)
                # _logger.info(f"Created KPI record for {user.name} on {target_date}")

        # _logger.info(f"Finished daily KPI calculation for {target_date}")

    @api.model
    def action_run_kpi_calculation_manually(self):
        """
        Public method to be called from a server action/button.
        This triggers the KPI calculation for the previous day.
        """
        _logger.info("KPI calculation triggered manually by a user.")
        
        today = fields.Date.context_today(self)
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        
        # set hardcoded date range for the last month
        first_day_last_month = datetime(2025, 5, 1, 23, 59, 59)
        last_day_last_month = datetime.now()

        date_iter = first_day_last_month
        while date_iter <= last_day_last_month:
            _logger.info(f"Calculating KPI for {date_iter}")
            self._cron_calculate_daily_kpi(date_iter)
            date_iter += timedelta(days=1)

        _logger.info("Manual KPI calculation finished.")
        
        # Return a notification to the user
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _("KPI calculation for yesterday has been completed successfully."),
                'type': 'success',
                'sticky': False,
            }
        }
