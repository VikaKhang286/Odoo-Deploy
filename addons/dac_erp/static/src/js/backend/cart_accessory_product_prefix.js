/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

// Keep the product search and Search More dialog untouched.  This changes only
// the selected value rendered in the sale-order-line table.
patch(Many2OneField.prototype, {
    setup() {
        super.setup(...arguments);
        const updateProduct = this.update;
        this.update = async (value, params) => {
            const result = await updateProduct(value, params);
            const record = this.props.record;
            const selected = value && value[0];
            if (
                this.props.name === "product_id" &&
                record?.resModel === "sale.order.line" &&
                record.data.order_type === "cart" &&
                selected?.id
            ) {
                const [product] = await this.orm.read(
                    "product.product", [selected.id], ["type"]
                );
                this.isCartAccessory = product.type === "cart_accessory";
                this.render();
            } else if (this.props.name === "product_id" && !selected) {
                this.isCartAccessory = false;
            }
            return result;
        };
    },
    get displayName() {
        const displayName = super.displayName;
        const record = this.props.record;
        if (
            this.props.name === "product_id" &&
            record?.resModel === "sale.order.line" &&
            record.data.order_type === "cart" &&
            (record.data.product_type === "cart_accessory" || this.isCartAccessory) &&
            displayName
        ) {
            return `+ ${displayName}`;
        }
        return displayName;
    },
});
