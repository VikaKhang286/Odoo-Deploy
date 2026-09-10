import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

class DacSaleDashboardApi(models.AbstractModel):
    _name = "dac.sale.dashboard.api"
    _description = "DAC Sale Dashboard - OWL API"

    @api.model
    def get_data(self, date_from=False, date_to=False, company_id=False):
        # Trả đúng dữ liệu từ service, nơi đã lọc theo owner/participants
        return self.env["sale.order"].dac_get_dashboard(date_from, date_to, company_id)