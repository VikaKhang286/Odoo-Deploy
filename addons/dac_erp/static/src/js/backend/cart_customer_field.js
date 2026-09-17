/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";

import { useInputField } from "@web/views/fields/input_field_hook";

export class CartCustomerField extends Many2OneField {
    static template = "dac_erp.CartCustomerField";

    setup() {
        super.setup();
        useInputField({
            refName: "customerAddress",
            fieldName: "customer_address",
            getValue: () => this.props.record.data.customer_address || "",
        });
        useInputField({
            refName: "customerPhone",
            fieldName: "phone",
            getValue: () => this.props.record.data.phone || "",
        });
    }

    onAddressKeydown(ev) {
        if (ev.key === "Enter") {
            ev.stopPropagation();
        }
    }
}

registry.category("fields").add("dac_cart_customer", {
    ...many2OneField,
    component: CartCustomerField,
});
