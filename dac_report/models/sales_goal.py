# -*- coding: utf-8 -*-
from odoo import api, fields, models

class DacSalesGoal(models.Model):
    _name = "dac.sales.goal"
    _description = "Sales Goal by Month"
    _order = "year desc, month desc, id desc"

    # --- BẮT BUỘC / KHÓA CHÍNH ---
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda s: s.env.company,
    )
    # Mục tiêu cá nhân: yêu cầu người phụ trách
    user_id = fields.Many2one(
        "res.users",
        string="Nhân viên",
        required=True,
        help="Mục tiêu cá nhân gán cho người dùng này.",
    )

    # --- KỲ MỤC TIÊU ---
    year = fields.Integer(required=True, string="Năm")
    # LƯU Ý: giữ kiểu chọn '1'..'12' như bản cũ để tương thích
    month = fields.Selection([(str(m), str(m)) for m in range(1, 13)],
                             required=True, string="Tháng")

    # --- DOANH THU MỤC TIÊU (giữ tên field cũ để không vỡ chỗ hook dashboard) ---
    target_amount = fields.Monetary(string="Mục tiêu doanh thu",
                                     currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
    )

    active = fields.Boolean(default=True)
    note = fields.Text(string="Ghi chú")

    # --- KPI ĐẾM (chỉ hiện fields, CHƯA tính toán) ---
    kpi_cared_count = fields.Integer(string="KH đã chăm sóc", default=0)
    kpi_quotation_count = fields.Integer(string="Số đơn báo giá", default=0)
    kpi_closed_count = fields.Integer(string="Số đơn đã chốt", default=0)
    kpi_completed_customer_count = fields.Integer(string="KH đã hoàn thành", default=0)

    # --- TRỌNG SỐ KPI (chỉ hiện fields, CHƯA tính toán) ---
    weight_revenue = fields.Float(string="Trọng số doanh thu", default=1.0)
    weight_cared = fields.Float(string="Trọng số KH chăm sóc", default=0.0)
    weight_quotation = fields.Float(string="Trọng số báo giá", default=0.0)
    weight_closed = fields.Float(string="Trọng số đơn đã chốt", default=0.0)
    weight_completed = fields.Float(string="Trọng số KH hoàn thành", default=0.0)

    # (tuỳ chọn) Ràng buộc một mục tiêu/tháng/năm cho mỗi user/company
    _sql_constraints = [
        (
            "goal_unique_user_period",
            "unique(company_id, user_id, year, month)",
            "Đã tồn tại mục tiêu cho nhân viên này trong tháng/năm chọn!",
        ),
    ]



    # Giữ hook cũ để dashboard gọi (không đổi logic)
    @api.model
    def get_goal(self, user, company, year, month):
        rec = self.sudo().search([
            ("user_id", "=", user.id),
            ("company_id", "=", company.id),
            ("year", "=", year),
            ("month", "=", str(month)),
            ("active", "=", True),
        ], limit=1)
        return rec.target_amount or 0.0



# Giữ hook để dashboard sử dụng (không thay đổi)
class SaleOrderDashboardGoal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dashboard_month_goal(self, year, month, company):
        return self.env["dac.sales.goal"].sudo().get_goal(
            self.env.user, company, year, str(month)
        )
