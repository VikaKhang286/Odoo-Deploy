/** @odoo-module **/
import { Component } from "@odoo/owl";

export class AttendanceMiniCalendar extends Component {
    static template = "dac_attendance.AttendanceMiniCalendar";
    static props = {
        days: Array,
        monthLabel: String,
    };

    get leadingBlanks() {
        if (!this.props.days.length) return [];
        // weekday: 0=Mon … 6=Sun → Mon is column 0
        const firstWeekday = this.props.days[0].weekday; // 0=Mon
        return Array.from({ length: firstWeekday });
    }

    dayTooltip(day) {
        const labels = {
            on_time: "Đúng giờ",
            late: `Trễ ${day.late_minutes || ""}p`,
            absent: "Vắng mặt",
            leave: "Nghỉ phép",
            weekend: "Cuối tuần",
            future: "",
        };
        return labels[day.status] || "";
    }
}
