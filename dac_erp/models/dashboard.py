from odoo import api, fields, models, _
from datetime import date as _date, timedelta
from odoo.exceptions import AccessError
import pytz

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_partner_vip_class(self, partner):
        """
        Trả về CSS class đặc biệt cho partner dựa trên tags Pancake.
        Hỗ trợ multiple classes nếu có cả 2 tags.
        Returns: 'vip-customer', 'loyal-customer', 'vip-customer loyal-customer', hoặc ''
        """
        if not partner or not partner.pancake_tag_ids:
            return ''
        
        tag_names = [tag.name.lower() for tag in partner.pancake_tag_ids]
        
        classes = []
        
        # Kiểm tra Khách lớn / VIP
        if 'khách lớn' in tag_names or 'vip' in tag_names:
            classes.append('vip-customer')
        
        # Kiểm tra Khách quen / Loyal
        if 'khách quen' in tag_names or 'loyal' in tag_names:
            classes.append('loyal-customer')
        
        # Trả về chuỗi classes (có thể là "vip-customer loyal-customer")
        return ' '.join(classes)

    #Dashboard Design
    @api.model
    def dac_get_dashboard_design(self):
        """
        Payload cho Design Dashboard:
        - ToDo: quotation
        - Designing: deposit
        - Done (week): design_done trong 7 ngày gần nhất
        - Due soon: deadline - today in [0..2] trên Designing
        """
        uid = self.env.uid
        user = self.env.user

        # quyền xem
        if user.has_group("dac_erp.group_dac_erp_manager"):
            base_domain = []
        elif user.has_group("dac_erp.group_dac_erp_design"):
            base_domain = [("user_id_design", "=", uid)]
        else:
            raise AccessError(_("Bạn không có quyền truy cập dashboard này."))

        today = _date.today()

        # ==== domain theo yêu cầu mới ====
        dom_todo       = base_domain + [("order_state_custom", "=", "quotation")]
        dom_designing  = base_domain + [("order_state_custom", "=", "deposit")]

        # ==== NEW: đơn CHƯA CÓ LINK THIẾT KẾ (deposit|production, chưa done) ====
        dom_missing_link = base_domain + [
            ("order_state_custom", "in", ["deposit", "production"]),
            ("design_done", "=", False),
            ("design_link", "=", False),
        ]

        # LOẠI đơn đã hoàn thành thiết kế khỏi 'Đang thiết kế'
        if "design_done" in self._fields:
            dom_designing += [("design_done", "=", False)]
        
        # done trong 7 ngày gần nhất (bấm "Hoàn thành" thiết kế)
        week_start     = today - timedelta(days=7)
        dom_done_week = base_domain + [
            ("order_state_custom", "in", ["deposit", "production"]),  # include 'production'
            ("write_date", ">=", week_start),
        ]
        if "design_done" in self._fields:
            dom_done_week += [("design_done", "=", True)]

        # query
        orders_todo = self.search(
            dom_todo,
            order="is_priority_today desc, is_priority desc, date asc",
        )
        orders_designing = self.search(
            dom_designing,
            order="is_priority_today desc, is_priority desc, design_deadline asc",
        )
        orders_missing = self.search(                           # NEW
            dom_missing_link,
            order="is_priority_today desc, is_priority desc, id desc",
        )
        # tránh trùng với cột Đang thiết kế (đơn deposit đang làm)
        if orders_designing:
            designing_ids = set(orders_designing.ids)
            orders_missing = orders_missing.filtered(lambda r: r.id not in designing_ids)

        # ---- ORDER: sắp xếp theo thời điểm hoàn thành (mới nhất trước)
        orders_done = self.search(
            dom_done_week,
            order="design_done_date desc, write_date desc, id desc"
        )
        done_week_count = self.search_count(dom_done_week)

        # helper: deadline mặc định (fallback khi chưa có trong DB)
        def _default_deadline(so):
            # Nếu đã có deadline thiết kế -> dùng luôn
            dl = getattr(so, "design_deadline", False)
            if dl:
                return dl
            # Fallback: có ngày phân công → base = ngày phân công
            base = getattr(so, "design_assigned_date", False)
            if base:
                return base if getattr(so, "is_priority_today", False) else (base + timedelta(days=3))
            return False

        # due soon?
        def _due_soon(so):
            dl = _default_deadline(so)
            if not dl:
                return False
            delta = (dl - today).days
            return 0 <= delta <= 2

        def _pack(so):
            dl = _default_deadline(so)
            today = _date.today()
            late_days = (today - dl).days if (dl and today > dl) else 0
            days_left = (dl - today).days if (dl and today <= dl) else False
            done_dt = getattr(so, "design_done_date", False)
            
            # 🆕 Kiểm tra VIP class
            vip_class = self._get_partner_vip_class(so.partner_id) if so.partner_id else ''
            
            return {
                "id": so.id,
                # nếu chưa có số ĐH thì để False (để frontend hiển thị 'Chưa có số ĐH')
                "order_number": getattr(so, "order_number", False) or False,
                "title": so.partner_id.display_name or so.name,
                "customer": so.partner_id.display_name or "",
                "deadline": dl,                          # vẫn giữ để tính KPI
                "deadline_str": dl.strftime("%d/%m/%Y") if dl else False,
                "done_date_str": done_dt.strftime("%d/%m/%Y") if done_dt else False,
                "days_left": days_left,                  # << thêm
                "late_days": late_days,
                "is_priority": bool(getattr(so, "is_priority", False)),
                "is_priority_today": bool(getattr(so, "is_priority_today", False)),
                "vip_class": vip_class,  # 🆕 CSS class
            }

        designing_list = [_pack(so) for so in orders_designing]

        data = {
            "kpi": {
                "new_pending": len(orders_todo),
                "in_progress": len(designing_list),
                "missing_link": len(orders_missing),      # NEW
                "due_soon": sum(1 for it in designing_list if _due_soon(self.browse(it["id"]))),
                "done_week": int(done_week_count),
            },
            "lists": {
                "todo": [_pack(so) for so in orders_todo],
                "designing": designing_list,
                "missing_link": [_pack(so) for so in orders_missing],   # NEW
                "done":      [_pack(so) for so in orders_done],  # << thêm
            },
            "user_name": user.name,
        }
        return data
    
    
    #Dashboard Production
    @api.model
    def dac_get_dashboard_production(self):
        """Payload cho Dashboard Sản xuất (phiên bản bám cờ production_done).

        Cột chính:
          - in_production:   đang ở 'production' và CHƯA production_done
          - done:            production_done = True (sort mới nhất)
          - pending_confirm: đã rời 'production' nhưng CHƯA production_done

        KPI:
          - in_production:   số đang SX
          - priority:        số ưu tiên (ưu tiên hoặc ưu tiên trong ngày)
          - overdue:         quá hạn SX (deadline < hôm nay)
          - due_soon:        sắp đến hạn (deadline - hôm nay ∈ [0..2])
          - unfinished:      rời SX nhưng chưa nhấn hoàn thành
          - finished_week:   production_done_date trong 7 ngày gần nhất
        """
        uid  = self.env.uid
        user = self.env.user

        # Quyền xem
        if user.has_group("dac_erp.group_dac_erp_production"):
            base_domain = [("user_id_production", "=", uid)]
        elif user.has_group("dac_erp.group_dac_erp_manager"):
            base_domain = []
        else:
            raise AccessError(_("Bạn không có quyền truy cập dashboard sản xuất."))

        # Mốc thời gian
        today       = _date.today()
        start_today = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago    = start_today - timedelta(days=7)

        # === DOMAIN CHUẨN ===
        # 1) Đang sản xuất & chưa hoàn thành
        dom_inprod = base_domain + [
            ("order_state_custom", "=", "production"),
            ("production_done", "=", False),
        ]
        # 2) Đã hoàn thành sản xuất
        dom_done = base_domain + [("production_done", "=", True)]
        dom_done_week = dom_done + [
            ("production_done_date", ">=", fields.Datetime.to_string(week_ago)),
        ]
        # 3) Đã rời 'production' nhưng chưa nhấn hoàn thành
        dom_left_not_done = base_domain + [
            ("order_state_custom", "in", ["delivery", "installation", "payment", "completed"]),
            ("production_done", "=", False),
            ("reached_production", "=", True),
        ]

        # Lấy dữ liệu
        orders_inprod  = self.search(
            dom_inprod,
            order="is_priority_today desc, is_priority desc, production_deadline asc, date_order asc, id asc",
        )
        orders_done    = self.search(dom_done, order="production_done_date desc", limit=50)
        orders_pending = self.search(dom_left_not_done, order="left_production_date desc, write_date desc", limit=50)

        # Helper pack
        def _pack(so):
            dl = getattr(so, "production_deadline", False)
            late_days  = (today - dl).days if (dl and today > dl) else 0
            days_left  = (dl - today).days if (dl and today <= dl) else False

            def _fmt_dt(dt):
                if not dt:
                    return False
                # context_timestamp cần naive → Datetime field của Odoo là naive UTC, ok
                dt_loc = fields.Datetime.context_timestamp(self, dt)
                return dt_loc.strftime("%d/%m/%Y %H:%M")
            
            # 🆕 Kiểm tra VIP class
            vip_class = self._get_partner_vip_class(so.partner_id) if so.partner_id else ''

            return {
                "id": so.id,
                "order_number": getattr(so, "order_number", False) or False,
                "title": so.partner_id.display_name or so.name,
                "customer_name": so.partner_id.display_name or "",
                "responsible_name": so.user_id_production.name if so.user_id_production else "—",
                "group_names": ", ".join(so.production_group_ids.mapped("name")) if so.production_group_ids else False,
                "deadline": dl,
                "deadline_str": dl.strftime("%d/%m/%Y") if dl else False,
                "days_left": days_left,
                "late_days": late_days,
                "is_priority": bool(getattr(so, "is_priority", False)),
                "is_priority_today": bool(getattr(so, "is_priority_today", False)),
                "done_date_str": _fmt_dt(getattr(so, "production_done_date", False)) or _fmt_dt(getattr(so, "left_production_date", False)),
                "vip_class": vip_class,  # 🆕 CSS class
            }

        data = {
            "kpi": {
                "in_production": self.search_count(dom_inprod),
                "priority": sum(1 for s in orders_inprod if s.is_priority or s.is_priority_today),
                "overdue_prod": sum(1 for s in orders_inprod if s.production_deadline and today > s.production_deadline),
                "due_soon": sum(1 for s in orders_inprod if s.production_deadline and 0 <= (s.production_deadline - today).days <= 2),
                "need_mark": self.search_count(dom_left_not_done),
                "finished_week": self.search_count(dom_done_week),
            },
            "lists": {
                "my_tasks":       [_pack(s) for s in orders_inprod],
                "all_tasks":      [_pack(s) for s in orders_inprod],  # thêm cho tab Lead
                "finished":       [_pack(s) for s in orders_done],
                "need_mark":      [_pack(s) for s in orders_pending],
            },
            "user_can_lead": user.has_group("base.group_system"),
        }
        return data
