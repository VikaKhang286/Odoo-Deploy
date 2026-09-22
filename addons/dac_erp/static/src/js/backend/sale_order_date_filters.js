/** @odoo-module **/

import { ControlPanel } from "@web/search/control_panel/control_panel";
import { patch } from "@web/core/utils/patch";

const SALE_DATE_FILTERS = new Set([
    "create_date_today",
    "create_date_yesterday",
    "create_date_this_week",
    "create_date_last_week",
    "create_date_last_month",
]);

patch(ControlPanel.prototype, {
    get showDacSaleDateFilters() {
        return this.env.searchModel?.resModel === "sale.order" && this.env.config.viewType === "list";
    },

    isDacSaleDateFilterActive(name) {
        return this.env.searchModel
            .getSearchItems((item) => item.type === "filter" && item.name === name)
            .some((item) => item.isActive);
    },

    onDacSaleDateFilterClick(name) {
        const items = this.env.searchModel.getSearchItems(
            (item) => item.type === "filter" && SALE_DATE_FILTERS.has(item.name)
        );
        const selected = items.find((item) => item.name === name);
        if (!selected) {
            return;
        }

        // These shortcuts are mutually exclusive. Clicking the active one clears it.
        for (const item of items) {
            if (item.id !== selected.id && item.isActive) {
                this.env.searchModel.toggleSearchItem(item.id);
            }
        }
        this.env.searchModel.toggleSearchItem(selected.id);
    },
});
