/** Keep the compiled Chatter inside the sale order sidebar group. */
import { patch } from "@web/core/utils/patch";
import { FormCompiler } from "@web/views/form/form_compiler";

patch(FormCompiler.prototype, {
    compile(node, params) {
        const result = super.compile(node, params);
        const chatterGroup = result.querySelector(".o-chatter-group");
        const chatter = result.querySelector(".o-mail-Form-chatter");

        if (chatterGroup && chatter && chatter.parentNode !== chatterGroup) {
            chatterGroup.append(chatter);
        }

        return result;
    },
});
