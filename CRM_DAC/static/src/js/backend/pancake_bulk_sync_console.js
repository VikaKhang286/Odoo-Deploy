/** @odoo-module **/

import { registry } from "@web/core/registry";

const LIVE_SECTION_ATTR = "data-pancake-live-section";
const REPORT_SECTION_ATTR = "data-pancake-report-section";
const CONSOLE_ROOT_SELECTOR = ".o_pancake_console_sheet";
const JSON_RPC_URL = "/web/dataset/call_kw/pancake.bulk.sync.dashboard/";
const LIVE_METHOD = "get_live_bulk_sync_snapshot_for_current_user";
const REPORT_METHOD = "get_bulk_sync_report_snapshot_for_current_user";

function getConsoleRoot() {
  return document.querySelector(CONSOLE_ROOT_SELECTOR);
}

function setSectionHtml(root, key, html, selector) {
  const target = root?.querySelector(`[${selector}="${key}"]`);
  if (!target || typeof html !== "string") {
    return;
  }
  target.innerHTML = html;
}

function setStateBanner(root, attrName, state, text) {
  const banner = root?.querySelector(`[${attrName}]`);
  if (!banner) {
    return;
  }
  banner.classList.remove(
    "o_pancake_console_live_state--idle",
    "o_pancake_console_live_state--live",
    "o_pancake_console_live_state--retrying"
  );
  banner.classList.add(`o_pancake_console_live_state--${state || "idle"}`);
  const textNode = banner.querySelector(".o_pancake_console_live_text");
  if (textNode) {
    textNode.textContent = text;
  }
}

async function jsonRpc(method) {
  const response = await fetch(`${JSON_RPC_URL}${method}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "same-origin",
    body: JSON.stringify({
      id: Date.now(),
      jsonrpc: "2.0",
      method: "call",
      params: {
        model: "pancake.bulk.sync.dashboard",
        method,
        args: [],
        kwargs: {},
      },
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload?.error?.data?.message || payload?.error?.message || `RPC failed for ${method}`);
  }
  return payload.result || {};
}

const state = {
  booted: false,
  root: null,
  detectTimer: null,
  liveTimer: null,
  reportTimer: null,
  liveBackoff: 2,
  reportBackoff: 5,
  destroyed: false,
};

function stopPolling() {
  if (state.liveTimer) {
    clearTimeout(state.liveTimer);
    state.liveTimer = null;
  }
  if (state.reportTimer) {
    clearTimeout(state.reportTimer);
    state.reportTimer = null;
  }
}

function resetRoot(root) {
  if (state.root === root) {
    return;
  }
  stopPolling();
  state.root = root;
  state.liveBackoff = 2;
  state.reportBackoff = 5;
}

function scheduleLive(delayMs) {
  if (state.destroyed) {
    return;
  }
  if (state.liveTimer) {
    clearTimeout(state.liveTimer);
  }
  state.liveTimer = window.setTimeout(fetchLiveSnapshot, delayMs);
}

function scheduleReport(delayMs) {
  if (state.destroyed) {
    return;
  }
  if (state.reportTimer) {
    clearTimeout(state.reportTimer);
  }
  state.reportTimer = window.setTimeout(fetchReportSnapshot, delayMs);
}

async function fetchLiveSnapshot() {
  const root = state.root || getConsoleRoot();
  if (!root || document.visibilityState === "hidden") {
    scheduleLive(5000);
    return;
  }
  try {
    const payload = await jsonRpc(LIVE_METHOD);
    const sections = payload?.sections || {};
    Object.entries(sections).forEach(([key, html]) => {
      setSectionHtml(root, key, html, LIVE_SECTION_ATTR);
    });
    const nextSeconds = Math.max(Number(payload?.poll_seconds || 15), 2);
    state.liveBackoff = 2;
    setStateBanner(
      root,
      "data-pancake-live-state",
      payload?.connection_state || "live",
      `Đang cập nhật live, lần tiếp theo sau ${nextSeconds} giây.`
    );
    scheduleLive(nextSeconds * 1000);
  } catch (error) {
    const retrySeconds = state.liveBackoff;
    state.liveBackoff = Math.min(state.liveBackoff * 2, 60);
    setStateBanner(
      root,
      "data-pancake-live-state",
      "retrying",
      `Mất kết nối cập nhật, đang thử lại sau ${retrySeconds} giây.`
    );
    scheduleLive(retrySeconds * 1000);
  }
}

async function fetchReportSnapshot() {
  const root = state.root || getConsoleRoot();
  if (!root || document.visibilityState === "hidden") {
    scheduleReport(10000);
    return;
  }
  try {
    const payload = await jsonRpc(REPORT_METHOD);
    const sections = payload?.sections || {};
    Object.entries(sections).forEach(([key, html]) => {
      setSectionHtml(root, key, html, REPORT_SECTION_ATTR);
    });
    const nextSeconds = Math.max(Number(payload?.poll_seconds || 30), 5);
    state.reportBackoff = 5;
    setStateBanner(
      root,
      "data-pancake-report-state",
      payload?.connection_state || "live",
      `Báo cáo đang được làm mới định kỳ, lần tiếp theo sau ${nextSeconds} giây.`
    );
    scheduleReport(nextSeconds * 1000);
  } catch (error) {
    const retrySeconds = state.reportBackoff;
    state.reportBackoff = Math.min(state.reportBackoff * 2, 60);
    setStateBanner(
      root,
      "data-pancake-report-state",
      "retrying",
      `Mất kết nối cập nhật báo cáo, đang thử lại sau ${retrySeconds} giây.`
    );
    scheduleReport(retrySeconds * 1000);
  }
}

function ensurePollingState() {
  const root = getConsoleRoot();
  if (!root) {
    resetRoot(null);
    return;
  }
  resetRoot(root);
  if (!state.liveTimer) {
    scheduleLive(0);
  }
  if (!state.reportTimer) {
    scheduleReport(0);
  }
}

function boot() {
  if (state.booted) {
    return;
  }
  state.booted = true;
  state.destroyed = false;
  ensurePollingState();
  state.detectTimer = window.setInterval(ensurePollingState, 1000);
  document.addEventListener("visibilitychange", ensurePollingState);
  window.addEventListener("hashchange", ensurePollingState);
  window.addEventListener("popstate", ensurePollingState);
}

const pancakeBulkSyncConsoleService = {
  start(env) {
    boot();
    env.bus.addEventListener("ACTION_MANAGER:AFTER", () => {
      window.setTimeout(ensurePollingState, 0);
    });
    const observer = new MutationObserver(() => ensurePollingState());
    observer.observe(document.body, { childList: true, subtree: true });
  },
};

registry.category("services").add("crm_dac_pancake_bulk_sync_console", pancakeBulkSyncConsoleService);
