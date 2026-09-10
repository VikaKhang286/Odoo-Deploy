/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { AttendanceMiniCalendar } from "./components/attendance_mini_calendar";
import { LeaveRequestDialog } from "./components/leave_request_dialog";
import { AmendmentRequestDialog } from "./components/amendment_request_dialog";

const WEEKDAYS_VI = ["Chủ nhật", "Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy"];
const MONTHS_VI = [
    "tháng 1","tháng 2","tháng 3","tháng 4","tháng 5","tháng 6",
    "tháng 7","tháng 8","tháng 9","tháng 10","tháng 11","tháng 12",
];

export class EmployeeDashboard extends Component {
    static template = "dac_attendance.EmployeeDashboard";
    static components = { AttendanceMiniCalendar };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            loading: true,
            error: null,
            actionLoading: false,
            data: {
                employee_name: "",
                today_status: { checked_in: false, check_in_time: "", today_hours: 0, is_late: false, late_minutes: 0 },
                month_calendar: [],
                month_label: "",
                leave_balance: {
                    annual: { used: 0, total: 12 },
                    sick: { used: 0, total: 5 },
                    unpaid: { used: 0, total: 3 },
                },
                pending_requests: [],
                history: [],
            },
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
                "dac_get_employee_dashboard",
                []
            );
            if (data.error) {
                this.state.error = data.error;
            } else {
                this.state.data = data;
            }
        } catch (e) {
            this.state.error = "Không tải được dữ liệu. Vui lòng thử lại.";
            console.error("EmployeeDashboard load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    get todayLabel() {
        const now = new Date();
        return `${WEEKDAYS_VI[now.getDay()]}, ${now.getDate()} ${MONTHS_VI[now.getMonth()]} ${now.getFullYear()}`;
    }

    formatHours(hours) {
        if (!hours) return "0h 00p";
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        return `${h}h ${String(m).padStart(2, "0")}p`;
    }

    remainingDays(type) {
        const bal = this.state.data.leave_balance[type];
        if (!bal) return 0;
        return Math.max(0, bal.total - (bal.used || 0));
    }

    leaveProgressStyle(type) {
        const bal = this.state.data.leave_balance[type];
        if (!bal || !bal.total) return "width:0%";
        const pct = Math.min(100, Math.round(((bal.used || 0) / bal.total) * 100));
        return `width:${pct}%`;
    }

    // ── Check-in / Check-out (reuse existing dac_check_in/out methods) ──────

    async onCheckIn() {
        this.state.actionLoading = true;
        try {
            const data = {};
            // Try to get GPS
            try {
                const pos = await this._getGPS();
                data.latitude = pos.coords.latitude;
                data.longitude = pos.coords.longitude;
                data.accuracy = pos.coords.accuracy;
            } catch (_) {}

            const result = await this.orm.call("hr.attendance", "dac_check_in", [data]);
            if (result.success) {
                this.notification.add(result.message, { type: "success" });
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Check-in thất bại", { type: "danger" });
            }
        } catch (e) {
            this.notification.add("Lỗi check-in: " + String(e.message || e), { type: "danger" });
        } finally {
            this.state.actionLoading = false;
        }
    }

    async onCheckOut() {
        this.state.actionLoading = true;
        try {
            const data = {};
            try {
                const pos = await this._getGPS();
                data.latitude = pos.coords.latitude;
                data.longitude = pos.coords.longitude;
            } catch (_) {}

            const result = await this.orm.call("hr.attendance", "dac_check_out", [data]);
            if (result.success) {
                this.notification.add(result.message, { type: "success" });
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Check-out thất bại", { type: "danger" });
            }
        } catch (e) {
            this.notification.add("Lỗi check-out: " + String(e.message || e), { type: "danger" });
        } finally {
            this.state.actionLoading = false;
        }
    }

    _getGPS() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) return reject(new Error("GPS không khả dụng"));
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: true, timeout: 8000, maximumAge: 60000,
            });
        });
    }

    // ── Dialogs ──────────────────────────────────────────────────────────────

    openLeaveDialog() {
        this.dialog.add(LeaveRequestDialog, {
            onSuccess: () => this.loadDashboard(),
        });
    }

    openAmendmentDialog() {
        this.dialog.add(AmendmentRequestDialog, {
            onSuccess: () => this.loadDashboard(),
        });
    }

    async onCancelRequest(type, id) {
        try {
            const result = await this.orm.call(
                "dac.attendance.dashboard",
                "dac_cancel_request",
                [type, id]
            );
            if (result.success) {
                this.notification.add("Đã hủy yêu cầu.", { type: "info" });
                await this.loadDashboard();
            } else {
                this.notification.add(result.message || "Không hủy được.", { type: "danger" });
            }
        } catch (e) {
            this.notification.add(String(e.message || e), { type: "danger" });
        }
    }
}

registry.category("actions").add("dac_attendance_employee_dashboard", EmployeeDashboard);
