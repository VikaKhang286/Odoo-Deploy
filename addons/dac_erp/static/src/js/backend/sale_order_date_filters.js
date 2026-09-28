/** @odoo-module **/

import { ControlPanel } from "@web/search/control_panel/control_panel";
import { patch } from "@web/core/utils/patch";
import { status } from "@odoo/owl";

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

    async onDacSaleDateFilterClick(name) {
        const searchModel = this.env.searchModel;
        const items = searchModel.getSearchItems(
            (item) => item.type === "filter" && SALE_DATE_FILTERS.has(item.name)
        );
        const selected = items.find((item) => item.name === name);
        if (!selected) {
            return;
        }

        // Apply the mutually exclusive shortcut as one search-model update. Without
        // batching, switching buttons reloads the list once to clear the old filter
        // and a second time to activate the new one, causing a visible white flash.
        searchModel.blockNotification = true;
        try {
            for (const item of items) {
                if (item.id !== selected.id && item.isActive) {
                    searchModel.toggleSearchItem(item.id);
                }
            }
            searchModel.toggleSearchItem(selected.id);
        } finally {
            searchModel.blockNotification = false;
        }
        await searchModel._notify();
        if (status(this) === "mounted") {
            this.render();
        }
    },
});
