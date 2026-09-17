/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";

export class CartCustomerField extends Many2OneField {
    static template = "dac_erp.CartCustomerField";
}

registry.category("fields").add("dac_cart_customer", {
    ...many2OneField,
    component: CartCustomerField,
});
