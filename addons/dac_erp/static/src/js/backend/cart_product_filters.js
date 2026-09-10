/** @odoo-module **/
import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

const cartFilters = new Set(["cart", "cart_foldable", "cart_accessory"]);
patch(SearchBarMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.cartFilterState = useState({ expanded: false });
    },
    get filterItems() {
        const displayedCartFilters = new Set();
        const items = super.filterItems.filter((item) => {
            if (!cartFilters.has(item.name)) {
                return true;
            }
            if (displayedCartFilters.has(item.name)) {
                return false;
            }
            displayedCartFilters.add(item.name);
            return true;
        });
        if (!['product.template', 'product.product'].includes(this.env.searchModel.resModel) ||
            !items.some((item) => item.name === "cart")) {
            return items;
        }
        const children = items.filter((item) =>
            ["cart_foldable", "cart_accessory"].includes(item.name));
        return items.filter((item) => !children.includes(item)).map((item) =>
            item.name === "cart" ? { ...item, cartChildren: children } : item);
    },
    onCartFilterSelected(itemId) {
        const items = this.env.searchModel.getSearchItems((item) =>
            item.type === "filter" && cartFilters.has(item.name));
        // Parent and children must not be OR'ed together: a child narrows the result.
        for (const item of items) {
            if (item.id !== itemId && item.isActive) {
                this.env.searchModel.toggleSearchItem(item.id);
            }
        }
        this.env.searchModel.toggleSearchItem(itemId);
    },
});
