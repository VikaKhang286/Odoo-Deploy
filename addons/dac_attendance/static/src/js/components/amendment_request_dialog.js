/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class AmendmentRequestDialog extends Component {
    static template = "dac_attendance.AmendmentRequestDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        prefillDate: { type: String, optional: true },
        onSuccess: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const today = new Date().toISOString().slice(0, 10);
        this.state = useState({
            targetDate: this.props.prefillDate || today,
            amendmentType: "missing_checkin",
            actualCheckIn: "",
            actualCheckOut: "",
            reason: "",
            submitting: false,
            errorMsg: "",
        });
    }

    get amendmentTypes() {
        return [
            { value: "missing_checkin", label: "Quên check-in" },
            { value: "missing_checkout", label: "Quên check-out" },
            { value: "both_missing", label: "Quên cả hai" },
            { value: "wrong_time", label: "Sai giờ" },
        ];
    }

    async onSubmit() {
        const { targetDate, amendmentType, actualCheckIn, actualCheckOut, reason } = this.state;
        if (!targetDate) {
            this.state.errorMsg = "Vui lòng chọn ngày cần điều chỉnh.";
            return;
        }
        if (!actualCheckIn) {
            this.state.errorMsg = "Vui lòng nhập giờ vào thực tế.";
            return;
        }
        if (!reason.trim()) {
            this.state.errorMsg = "Vui lòng nhập lý do.";
            return;
        }
        this.state.errorMsg = "";
        this.state.submitting = true;

        // Convert local datetime-local value to UTC ISO string
        const toUtcIso = (localStr) => {
            if (!localStr) return false;
            return new Date(localStr).toISOString().replace("T", " ").slice(0, 19);
        };

        try {
            const result = await this.orm.call(
                "dac.attendance.dashboard",
                "dac_submit_amendment",
                [{
                    target_date: targetDate,
                    amendment_type: amendmentType,
                    actual_check_in: toUtcIso(actualCheckIn),
                    actual_check_out: toUtcIso(actualCheckOut) || false,
                    reason,
                }]
            );
            if (result.success) {
                this.notification.add("Đã gửi yêu cầu điều chỉnh thành công!", { type: "success" });
                if (this.props.onSuccess) this.props.onSuccess();
                this.props.close();
            } else {
                this.state.errorMsg = result.message || "Không gửi được yêu cầu.";
            }
        } catch (e) {
            this.state.errorMsg = String(e.message || e);
        } finally {
            this.state.submitting = false;
        }
    }
}
