/** @odoo-module **/
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { registry } from "@web/core/registry";

export class PancakeMany2OneField extends Many2OneField {
    get isPancakeCustomer() {
        return !!(this.props.record?.data?.partner_is_pancake);
    }
}
PancakeMany2OneField.template = "CRM_DAC.PancakeMany2OneField";

registry.category("fields").add("pancake_many2one", {
    ...many2OneField,
    component: PancakeMany2OneField,
});
