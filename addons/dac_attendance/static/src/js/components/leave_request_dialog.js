/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class LeaveRequestDialog extends Component {
    static template = "dac_attendance.LeaveRequestDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSuccess: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            leaveType: "annual",
            dateFrom: "",
            dateTo: "",
            reason: "",
            submitting: false,
            errorMsg: "",
        });
    }

    get leaveTypes() {
        return [
            { value: "annual", label: "Phép năm" },
            { value: "sick", label: "Phép bệnh" },
            { value: "unpaid", label: "Không lương" },
            { value: "other", label: "Khác" },
        ];
    }

    get numberOfDays() {
        if (!this.state.dateFrom || !this.state.dateTo) return 0;
        const from = new Date(this.state.dateFrom);
        const to = new Date(this.state.dateTo);
        const diff = Math.round((to - from) / 86400000) + 1;
        return diff > 0 ? diff : 0;
    }

    async onSubmit() {
        const { leaveType, dateFrom, dateTo, reason } = this.state;
        if (!dateFrom || !dateTo) {
            this.state.errorMsg = "Vui lòng chọn ngày bắt đầu và kết thúc.";
            return;
        }
        if (new Date(dateTo) < new Date(dateFrom)) {
            this.state.errorMsg = "Ngày kết thúc phải sau ngày bắt đầu.";
            return;
        }
        if (!reason.trim()) {
            this.state.errorMsg = "Vui lòng nhập lý do nghỉ phép.";
            return;
        }
        this.state.errorMsg = "";
        this.state.submitting = true;
        try {
            const result = await this.orm.call(
                "dac.attendance.dashboard",
                "dac_submit_leave",
                [{ leave_type: leaveType, date_from: dateFrom, date_to: dateTo, reason }]
            );
            if (result.success) {
                this.notification.add("Đã gửi đơn nghỉ phép thành công!", { type: "success" });
                if (this.props.onSuccess) this.props.onSuccess();
                this.props.close();
            } else {
                this.state.errorMsg = result.message || "Không gửi được đơn.";
            }
        } catch (e) {
            this.state.errorMsg = String(e.message || e);
        } finally {
            this.state.submitting = false;
        }
    }
}
