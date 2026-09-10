/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

// Patch FormController to hide header buttons for specific views
patch(FormController.prototype, {
  setup() {
    super.setup();

    // Check if this is our specific account.move inherited view
    if (
      this.props.resModel === "account.move" &&
      this.props.context?.default_move_type &&
      this.props.viewId &&
      this.props.viewId.toString().includes("dac_erp")
    ) {
      // Hide header buttons after view is loaded
      this.onMounted(() => {
        this.hideHeaderButtonsForMove();
      });
    }

    // Check if this is our specific account.payment inherited view
    if (
      this.props.resModel === "account.payment" &&
      this.props.viewId &&
      this.props.viewId.toString().includes("dac_erp")
    ) {
      // Hide header buttons after view is loaded
      this.onMounted(() => {
        this.hideHeaderButtonsForPayment();
      });
    }
  },

  hideHeaderButtonsForMove() {
    // Find and hide the status bar buttons container
    const statusBarButtons = this.el?.querySelector(".o_statusbar_buttons");
    if (statusBarButtons) {
      statusBarButtons.style.display = "none";
    }

    // Also hide individual buttons as backup
    const buttonsToHide = [
      'button[name="action_post"]',
      'button[name="action_register_payment"]',
      'button[id="account_invoice_payment_btn"]',
      'button[id="account_invoice_payment_secondary_btn"]',
      'button[name="action_invoice_sent"]',
      'button[name="button_cancel"]',
    ];

    buttonsToHide.forEach((selector) => {
      const buttons = this.el?.querySelectorAll(`header ${selector}`);
      buttons?.forEach((button) => {
        button.style.display = "none";
      });
    });
  },

  hideHeaderButtonsForPayment() {
    // Find and hide the status bar buttons container
    const statusBarButtons = this.el?.querySelector(".o_statusbar_buttons");
    if (statusBarButtons) {
      statusBarButtons.style.display = "none";
    }

    // Also hide individual buttons as backup for payment
    const buttonsToHide = [
      'button[name="action_post"]',
      'button[name="action_validate"]',
      'button[name="action_reject"]',
      'button[name="action_draft"]',
      'button[name="action_cancel"]',
      'button[name="button_request_cancel"]',
      'button[name="mark_as_sent"]',
      'button[name="unmark_as_sent"]',
    ];

    buttonsToHide.forEach((selector) => {
      const buttons = this.el?.querySelectorAll(`header ${selector}`);
      buttons?.forEach((button) => {
        button.style.display = "none";
      });
    });
  },
});
