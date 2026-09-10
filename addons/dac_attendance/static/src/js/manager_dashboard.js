/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const WEEKDAYS_VI = ["Chủ nhật", "Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy"];
const MONTHS_VI = [
    "tháng 1","tháng 2","tháng 3","tháng 4","tháng 5","tháng 6",
    "tháng 7","tháng 8","tháng 9","tháng 10","tháng 11","tháng 12",
];

const EMPTY_DATA = {
    today_stats: { present: 0, absent: 0, late: 0, pending_approvals: 0 },
    present_list: [],
    absent_list: [],
    pending_approvals: { leaves: [], amendments: [] },
};

export class ManagerDashboard extends Component {
    static template = "dac_attendance.ManagerDashboard";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: null,
            data: EMPTY_DATA,
            activeTab: "present",
            approvalTab: "leaves",
            processingId: null,
            refuseTarget: null,   // { type: 'leave'|'amendment', id }
            refuseReason: "",
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "dac.attendance.dashboard",
                "dac_get_manager_dashboard",
                []
            );
            this.state.data = data;
        } catch (e) {
            this.state.error = "Không tải được dữ liệu. Bạn có quyền Quản lý chấm công không?";
            console.error("ManagerDashboard load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    get todayLabel() {
        const now = new Date();
        return `${WEEKDAYS_VI[now.getDay()]}, ${now.getDate()} ${MONTHS_VI[now.getMonth()]} ${now.getFullYear()}`;
    }

    get lateList() {
        return (this.state.data.present_list || []).filter(e => e.is_late);
    }

    // ── Approve ──────────────────────────────────────────────────────────────

    async onApproveLeave(leaveId) {
        this.state.processingId = leaveId;
        try {
            const result = await this.orm.call(
                "dac.attendance.dashboard", "dac_approve_leave", [leaveId]);
            if (result.success) {
                this.notification.add("Đã duyệt đơn nghỉ phép.", { type: "success" });
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Duyệt thất bại.", { type: "danger" });
            }
        } catch (e) {
            this.notification.add(String(e.message || e), { type: "danger" });
        } finally {
            this.state.processingId = null;
        }
    }

    async onApproveAmendment(amendId) {
        this.state.processingId = amendId;
        try {
            const result = await this.orm.call(
                "dac.attendance.dashboard", "dac_approve_amendment", [amendId]);
            if (result.success) {
                this.notification.add("Đã duyệt và cập nhật bản ghi chấm công.", { type: "success" });
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Duyệt thất bại.", { type: "danger" });
            }
        } catch (e) {
            this.notification.add(String(e.message || e), { type: "danger" });
        } finally {
            this.state.processingId = null;
        }
    }

    // ── Refuse (2-step: open inline form, then confirm) ───────────────────────

    onRefuseItem(type, id) {
        this.state.refuseTarget = { type, id };
        this.state.refuseReason = "";
    }

    async confirmRefuse() {
        const { type, id } = this.state.refuseTarget;
        const reason = this.state.refuseReason;
        this.state.processingId = id;
        try {
            const method = type === "leave" ? "dac_refuse_leave" : "dac_refuse_amendment";
            const result = await this.orm.call(
                "dac.attendance.dashboard", method, [id, reason]);
            if (result.success) {
                this.notification.add("Đã từ chối yêu cầu.", { type: "info" });
                this.state.refuseTarget = null;
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Từ chối thất bại.", { type: "danger" });
            }
        } catch (e) {
            this.notification.add(String(e.message || e), { type: "danger" });
        } finally {
            this.state.processingId = null;
        }
    }

    // ── Reports ───────────────────────────────────────────────────────────────

    openReports() {
        this.action.doAction("dac_attendance.action_dac_attendance_report");
    }
}

registry.category("actions").add("dac_attendance_manager_dashboard", ManagerDashboard);
