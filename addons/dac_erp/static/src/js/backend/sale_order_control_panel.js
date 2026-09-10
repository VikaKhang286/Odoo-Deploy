/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const SLOT_CLASS = "dac-sale-order-control-panel-slot";
const ACTIVE_CLASS = "dac-sale-order-control-panel-active";
const FLOATING_MENU_CLASS = "dac-title-actions-menu--floating";
const STATE_CLASS_PREFIX = "dac-order-state-";

function isSaleOrderForm(controller) {
  return controller.props?.resModel === "sale.order";
}

function getControlPanel(controller) {
  const actionManager = getActionManager(controller);
  if (actionManager) {
    return actionManager.querySelector(".o_control_panel");
  }
  return document.querySelector(".o_control_panel");
}

function getActionManager(controller) {
  return controller.el?.closest(".o_action_manager") || document.querySelector(".o_action_manager");
}

function getSourceBar(controller) {
  return (
    controller.el?.querySelector(".dac-control-panel-bar") ||
    document.querySelector(".dac-sale-form .dac-control-panel-bar")
  );
}

function getCurrentOrderState(controller) {
  const sourceBar = getSourceBar(controller);
  const currentStep = sourceBar?.querySelector(".dac-control-panel-progress .o_arrow_button_current[data-value]");
  return currentStep?.dataset.value || null;
}

function syncStateClass(target, state) {
  if (!target) {
    return;
  }

  for (const className of Array.from(target.classList)) {
    if (className.startsWith(STATE_CLASS_PREFIX)) {
      target.classList.remove(className);
    }
  }

  if (state) {
    target.classList.add(`${STATE_CLASS_PREFIX}${state}`);
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function resetActionMenuPosition(menu) {
  menu.classList.remove(FLOATING_MENU_CLASS);
  menu.style.position = "";
  menu.style.left = "";
  menu.style.top = "";
  menu.style.right = "";
  menu.style.bottom = "";
  menu.style.inset = "";
  menu.style.transform = "";
  menu.style.maxWidth = "";
}

function positionActionMenu(toggle, menu) {
  if (!toggle || !menu) {
    return;
  }

  menu.classList.add(FLOATING_MENU_CLASS);
  menu.style.position = "fixed";
  menu.style.inset = "auto";
  menu.style.transform = "none";
  menu.style.maxWidth = `${Math.max(window.innerWidth - 32, 220)}px`;

  const toggleRect = toggle.getBoundingClientRect();
  const menuWidth = menu.offsetWidth || menu.scrollWidth || 260;
  const left = clamp(toggleRect.right - menuWidth, 16, window.innerWidth - menuWidth - 16);
  const top = clamp(toggleRect.bottom + 8, 16, window.innerHeight - menu.offsetHeight - 16);

  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.right = "auto";
  menu.style.bottom = "auto";
}

patch(FormController.prototype, {
  setup() {
    super.setup();

    if (!isSaleOrderForm(this)) {
      return;
    }

    this.__dacSaleControlPanelRetries = 0;

    onMounted(() => {
      this.mountSaleOrderControlPanel();
      this.syncSaleOrderDirtyState();
    });

    onPatched(() => {
      this.mountSaleOrderControlPanel();
      this.syncSaleOrderDirtyState();
    });

    onWillUnmount(() => {
      this.cleanupSaleOrderControlPanel();
    });
  },

  mountSaleOrderControlPanel() {
    const controlPanel = getControlPanel(this);
    const sourceBar = getSourceBar(this);
    if (!controlPanel || !sourceBar) {
      if (this.__dacSaleControlPanelRetries < 10) {
        this.__dacSaleControlPanelRetries += 1;
        window.setTimeout(() => this.mountSaleOrderControlPanel(), 100);
      }
      return;
    }

    this.__dacSaleControlPanelRetries = 0;

    let slot = controlPanel.querySelector(`.${SLOT_CLASS}`);
    if (!slot) {
      slot = document.createElement("div");
      slot.className = SLOT_CLASS;
      controlPanel.appendChild(slot);
    }

    if (sourceBar.parentElement !== slot) {
      slot.replaceChildren(sourceBar);
    }

    controlPanel.classList.add(ACTIVE_CLASS);
    this.syncSaleOrderStateClass();
    this.bindSaleOrderActionMenu();
    this.syncSaleOrderDirtyState();
  },

  cleanupSaleOrderControlPanel() {
    this.unbindSaleOrderActionMenu();
    this.clearSaleOrderStateClass();

    const controlPanel = getControlPanel(this);
    if (!controlPanel) {
      return;
    }

    controlPanel.classList.remove(ACTIVE_CLASS);
    controlPanel.querySelector(`.${SLOT_CLASS}`)?.remove();
  },

  bindSaleOrderActionMenu() {
    const sourceBar = getSourceBar(this);
    const dropdown = sourceBar?.querySelector(".dac-control-panel-tools");
    const toggle = dropdown?.querySelector(".dac-title-actions-toggle");
    const menu = dropdown?.querySelector(".dac-title-actions-menu");

    if (!dropdown || !toggle || !menu) {
      return;
    }

    if (this.__dacSaleActionMenuDropdown === dropdown) {
      if (menu.classList.contains("show")) {
        positionActionMenu(toggle, menu);
      }
      return;
    }

    this.unbindSaleOrderActionMenu();

    const onShown = () => {
      window.requestAnimationFrame(() => positionActionMenu(toggle, menu));
    };
    const onHidden = () => {
      resetActionMenuPosition(menu);
    };
    const onResize = () => {
      if (menu.classList.contains("show")) {
        positionActionMenu(toggle, menu);
      }
    };

    dropdown.addEventListener("shown.bs.dropdown", onShown);
    dropdown.addEventListener("hidden.bs.dropdown", onHidden);
    window.addEventListener("resize", onResize);

    this.__dacSaleActionMenuDropdown = dropdown;
    this.__dacSaleActionMenuCleanup = () => {
      dropdown.removeEventListener("shown.bs.dropdown", onShown);
      dropdown.removeEventListener("hidden.bs.dropdown", onHidden);
      window.removeEventListener("resize", onResize);
      resetActionMenuPosition(menu);
    };
  },

  unbindSaleOrderActionMenu() {
    this.__dacSaleActionMenuCleanup?.();
    this.__dacSaleActionMenuCleanup = null;
    this.__dacSaleActionMenuDropdown = null;
  },

  syncSaleOrderDirtyState() {
    const isDirty = this.model?.root?.isDirty ?? false;
    const saveBtn = document.querySelector(
      ".dac-sale-order-control-panel-slot button[name='action_save_custom'], " +
      ".dac-control-panel-bar button[name='action_save_custom']"
    );
    if (saveBtn) {
      saveBtn.classList.toggle("dac-save-btn-dirty", isDirty);
    }
  },

  syncSaleOrderStateClass() {
    const state = getCurrentOrderState(this);
    syncStateClass(document.body, state);
    syncStateClass(document.querySelector(".o_web_client"), state);
    syncStateClass(document.querySelector(".dac-sale-form"), state);
    syncStateClass(this.el, state);
    syncStateClass(getActionManager(this), state);
    syncStateClass(getControlPanel(this), state);
  },

  clearSaleOrderStateClass() {
    syncStateClass(document.body, null);
    syncStateClass(document.querySelector(".o_web_client"), null);
    syncStateClass(document.querySelector(".dac-sale-form"), null);
    syncStateClass(this.el, null);
    syncStateClass(getActionManager(this), null);
    syncStateClass(getControlPanel(this), null);
  },
});
