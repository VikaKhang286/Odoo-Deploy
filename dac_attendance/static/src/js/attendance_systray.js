/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";

export class DacAttendanceSystray extends Component {
    static template = "dac_attendance.AttendanceSystray";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            checkedIn: false,
            checkInTime: false,
            todayHours: 0.0,
            hasEmployee: false,
            hasConfig: false,
            checkInMethod: "location",
            loading: false,
            employeeName: "",
            checkoutNeedsConfirmation: false,
            earlyMinutes: 0,
            isLate: false,
            lateMinutes: 0,
        });

        onWillStart(async () => {
            await this.loadConfig();
        });
    }

    async loadConfig() {
        try {
            const result = await this.orm.call(
                "hr.employee.attendance.config",
                "get_config_for_current_user",
                []
            );
            if (result) {
                this.state.hasEmployee = result.has_employee;
                this.state.hasConfig = result.has_config;
                this.state.checkInMethod = result.check_in_method || "location";
                this.state.employeeName = result.employee_name || "";

                if (result.has_employee && result.employee_id) {
                    this.state.checkedIn = result.checked_in || false;
                    this.state.checkInTime = result.check_in_time_display || result.check_in_time || false;
                    this.state.todayHours = result.today_hours !== undefined ? result.today_hours : 0.0;
                    this.state.isLate = Boolean(result.is_late);
                    this.state.lateMinutes = result.late_minutes || 0;
                    await this._loadCheckoutState();
                } else {
                    this.state.checkoutNeedsConfirmation = false;
                    this.state.earlyMinutes = 0;
                    this.state.isLate = false;
                    this.state.lateMinutes = 0;
                }
            }
        } catch (e) {
            console.error("DAC Attendance: failed to load config", e);
        }
    }

    async _loadCheckoutState() {
        if (!this.state.checkedIn) {
            this.state.checkoutNeedsConfirmation = false;
            this.state.earlyMinutes = 0;
            return;
        }
        try {
            const result = await this.orm.call(
                "hr.attendance",
                "dac_get_checkout_confirmation_info",
                []
            );
            this.state.checkoutNeedsConfirmation = Boolean(result?.needs_confirmation);
            this.state.earlyMinutes = result?.early_minutes || 0;
        } catch (e) {
            console.warn("DAC Attendance: failed to load checkout state", e);
            this.state.checkoutNeedsConfirmation = false;
            this.state.earlyMinutes = 0;
        }
    }

    // ---- Pill button computed state ----

    get boxClass() {
        if (this.state.loading) return "o_dac_attendance_box--loading";
        if (this.state.checkedIn) return "o_dac_attendance_box--working";
        if (this.isLateCheckInWindow) return "o_dac_attendance_box--late";
        return "o_dac_attendance_box--ready";
    }

    get statusLabel() {
        if (!this.state.hasEmployee) return "CHẤM CÔNG";
        if (this.state.loading) return "Đang xử lý...";
        return this.state.checkedIn ? "ĐANG LÀM VIỆC" : "SẴN SÀNG CHẤM CÔNG";
    }

    get statusSubText() {
        if (!this.state.checkedIn) return "";
        const parts = [];
        if (this.state.checkInTime) {
            if (typeof this.state.checkInTime === "string" && /^\d{2}:\d{2}$/.test(this.state.checkInTime)) {
                parts.push(this.state.checkInTime);
            } else {
                const t = new Date(this.state.checkInTime);
                if (!Number.isNaN(t.getTime())) {
                    const hh = String(t.getHours()).padStart(2, "0");
                    const mm = String(t.getMinutes()).padStart(2, "0");
                    parts.push(`${hh}:${mm}`);
                }
            }
        }
        return parts.join(" • ");
    }

    get statusTitle() {
        if (!this.state.hasEmployee) return "Không có hồ sơ nhân viên";
        return this.state.checkedIn
            ? "Đang làm việc - Có thể check-out"
            : "Chưa check-in - Có thể check-in";
    }

    get actionLabel() {
        if (this.state.loading) return "Đang xử lý...";
        if (this.state.checkedIn) return "Check out";
        return this.isLateCheckInWindow ? "Check in trễ" : "Check in";
    }

    get actionButtonClass() {
        const classes = ["o_dac_attendance_action"];
        if (this.state.checkedIn) {
            classes.push("o_dac_attendance_action--checkout");
            if (this.state.checkoutNeedsConfirmation) {
                classes.push("o_dac_attendance_action--early");
            }
        } else {
            classes.push("o_dac_attendance_action--checkin");
            if (this.isLateCheckInWindow) {
                classes.push("o_dac_attendance_action--late");
            }
        }
        if (this.state.loading) {
            classes.push("o_dac_attendance_action--loading");
        }
        return classes.join(" ");
    }

    get statusMetaText() {
        if (!this.state.hasEmployee) {
            return "Bạn chưa có hồ sơ nhân viên";
        }
        if (this.state.loading) {
            return "Đang xử lý dữ liệu chấm công";
        }
        if (this.state.checkedIn) {
            if (this.state.isLate) {
                return `Hôm nay vào trễ ${this.state.lateMinutes} phút`;
            }
            if (this.state.checkoutNeedsConfirmation) {
                return "Đang trong ca làm việc";
            }
            return "Đủ điều kiện check out";
        }
        if (this.isLateCheckInWindow) {
            return "Bạn đang trong khung giờ check in trễ";
        }
        return "Nhấn Check in để bắt đầu ca làm";
    }

    get isLateCheckInWindow() {
        if (this.state.checkedIn || !this.state.hasEmployee) {
            return false;
        }
        const hour = new Date().getHours();
        return hour >= 8 && hour < 12;
    }

    // ---- Click handler ----

    async onClickAttendance(isCheckOut = this.state.checkedIn) {
        if (this.state.loading) return;
        if (!this.state.hasEmployee) {
            this.notification.add("Bạn chưa có hồ sơ nhân viên trong hệ thống.", {
                type: "warning",
            });
            return;
        }

        const method = this.state.checkInMethod;

        if (isCheckOut) {
            const shouldContinue = await this._confirmEarlyCheckoutIfNeeded();
            if (!shouldContinue) {
                return;
            }
        }

        if (method === "photo") {
            await this._handlePhotoMethod(isCheckOut);
        } else {
            await this._handleLocationMethod(isCheckOut);
        }
    }

    async onClickCheckIn() {
        await this.onClickAttendance(false);
    }

    async onClickCheckOut() {
        await this.onClickAttendance(true);
    }

    async _handleLocationMethod(isCheckOut) {
        this.state.loading = true;
        try {
            const data = {};

            // Try to get GPS from browser
            try {
                const pos = await this._getGPSPosition();
                data.latitude = pos.coords.latitude;
                data.longitude = pos.coords.longitude;
                data.accuracy = pos.coords.accuracy;
            } catch (e) {
                console.warn("GPS not available:", e.message);
            }

            const methodName = isCheckOut ? "dac_check_out" : "dac_check_in";
            const result = await this.orm.call("hr.attendance", methodName, [data]);

            if (result.success) {
                const msg = this._buildSuccessMessage(result, isCheckOut);
                this.notification.add(msg, { type: "success" });
                await this.loadConfig();
            } else {
                this.notification.add(result.message || "Lỗi không xác định", {
                    type: "danger",
                });
            }
        } catch (e) {
            this.notification.add(`Lỗi: ${e.message}`, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async _handlePhotoMethod(isCheckOut) {
        const { DacAttendanceCameraDialog } = await import(
            "@dac_attendance/js/attendance_camera_dialog"
        );
        this.dialog.add(DacAttendanceCameraDialog, {
            isCheckOut,
            employeeName: this.state.employeeName,
            onPhotoTaken: async (photoBase64, metadata) => {
                await this._submitPhoto(photoBase64, metadata, isCheckOut);
            },
        });
    }

    async _submitPhoto(photoBase64, metadata, isCheckOut) {
        this.state.loading = true;
        try {
            const data = {
                photo_base64: photoBase64,
                photo_metadata: metadata,
            };
            const methodName = isCheckOut ? "dac_check_out" : "dac_check_in";
            const result = await this.orm.call("hr.attendance", methodName, [data]);

            if (result.success) {
                const msg = this._buildSuccessMessage(result, isCheckOut);
                this.notification.add(msg, { type: "success" });
                await this.loadConfig();
            } else {
                this.notification.add(result.message || "Lỗi không xác định", {
                    type: "danger",
                });
            }
        } catch (e) {
            this.notification.add(`Lỗi: ${e.message}`, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    _buildSuccessMessage(result, isCheckOut) {
        if (isCheckOut) {
            let msg = `Check-out thành công! Số giờ làm: ${result.worked_hours}h`;
            if (result.is_early_leave) {
                msg += " Bạn đã check-out sớm, hệ thống đã ghi nhận lại.";
            }
            return msg;
        }

        if (result.is_late) {
            return `Bạn đã đi làm trễ ${result.late_minutes || 0} phút, hãy chú ý thời gian làm việc nhé!`;
        }
        return "Chúc mừng bạn đã đi làm đúng giờ, hãy tiếp tục phát huy nhé";
    }

    async _confirmEarlyCheckoutIfNeeded() {
        const result = await this.orm.call(
            "hr.attendance",
            "dac_get_checkout_confirmation_info",
            []
        );

        if (!result || !result.needs_confirmation) {
            return true;
        }

        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: "Xác nhận check-out sớm",
                body: result.message || "Bạn có muốn check-out sớm không?",
                confirmLabel: "Check-out sớm",
                cancelLabel: "Hủy",
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
    }

    _getGPSPosition() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error("Trình duyệt không hỗ trợ GPS"));
                return;
            }
            navigator.geolocation.getCurrentPosition(resolve, reject, {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 60000,
            });
        });
    }
}

// Remove default Odoo attendance systray icon to avoid duplicates
const systrayRegistry = registry.category("systray");
for (const key of Object.keys(systrayRegistry.content || {})) {
    if (key.includes("hr_attendance") || key === "AttendanceSystray") {
        try {
            systrayRegistry.remove(key);
        } catch (e) {
            console.error("Failed to remove Odoo default attendance icon:", e);
        }
    }
}

registry.category("systray").add("dac_attendance.AttendanceSystray", {
    Component: DacAttendanceSystray,
}, { sequence: 25 });

