/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { onPatched, onWillUnmount } from "@odoo/owl";

// Fields that trigger auto-save when changed (sale.order form only)
const AUTO_SAVE_FIELDS = [
    "user_id_design",
    "user_id_production",
    "design_deadline",
    "production_deadline",
    "production_group_ids",
];

function extractFieldKey(val) {
    if (val === false || val === null || val === undefined) return "";
    if (Array.isArray(val)) {
        // Many2many: array of record-like objects
        return val
            .map((r) => r?.resId ?? r?.id ?? String(r))
            .sort()
            .join(",");
    }
    if (typeof val === "object") {
        // Many2one DataPoint
        if ("resId" in val) return String(val.resId ?? "");
        if ("id" in val) return String(val.id ?? "");
        // Luxon DateTime
        if (typeof val.toISO === "function") return val.toISO();
        return JSON.stringify(val);
    }
    return String(val);
}

patch(FormController.prototype, {
    setup() {
        super.setup();

        if (this.props?.resModel !== "sale.order") {
            return;
        }

        this.__dacAutoSaveSig = null;
        this.__dacAutoSaveTimer = null;

        const getSig = () => {
            const record = this.model?.root;
            if (!record?.data || !record.resId) return null;
            return AUTO_SAVE_FIELDS.map((f) => extractFieldKey(record.data[f])).join("|");
        };

        onPatched(() => {
            const sig = getSig();
            if (sig === null) return;

            if (this.__dacAutoSaveSig !== null && sig !== this.__dacAutoSaveSig) {
                clearTimeout(this.__dacAutoSaveTimer);
                this.__dacAutoSaveTimer = setTimeout(async () => {
                    try {
                        if (this.model?.root?.isDirty) {
                            await this.save();
                        }
                    } catch (_e) {
                        // Validation errors are shown natively by Odoo
                    }
                }, 700);
            }

            this.__dacAutoSaveSig = sig;
        });

        onWillUnmount(() => {
            clearTimeout(this.__dacAutoSaveTimer);
        });
    },
});
