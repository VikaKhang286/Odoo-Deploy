/** @odoo-module **/
import { WebClient } from "@web/webclient/webclient";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { onWillStart, onMounted } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

function hasDebugParam() {
  const sp = new URLSearchParams(window.location.search);
  return sp.has("debug") || sp.has("debugMode");
}

function clearDebugCookies() {
  const past = "Thu, 01 Jan 1970 00:00:00 GMT";
  for (const n of ["debug", "odoo-debug", "debugMode"]) {
    document.cookie = `${n}=; expires=${past}; path=/`;
  }
}

function stripDebugFromUrl() {
  const url = new URL(window.location.href);
  const hadDebug =
    url.searchParams.has("debug") || url.searchParams.has("debugMode");

  url.searchParams.delete("debug");
  url.searchParams.delete("debugMode");

  if (hadDebug) {
    // Replace URL without reload
    const newUrl = url.pathname + url.search + url.hash;
    window.history.replaceState(null, "", newUrl);
    console.log("[DEBUG_GUARD] Stripped debug params from URL");
    return true;
  }
  return false;
}

function monitorAndBlockDebug(isAdmin) {
  if (isAdmin) return; // Admin được phép debug

  // Monitor URL changes (for SPA navigation)
  const observer = new MutationObserver(() => {
    if (!isAdmin && hasDebugParam()) {
      console.log("[DEBUG_GUARD] Debug param detected - removing");
      clearDebugCookies();
      stripDebugFromUrl();
    }
  });

  observer.observe(document, {
    subtree: true,
    childList: true,
  });

  // Monitor URL changes via pushState/replaceState
  const originalPushState = window.history.pushState;
  const originalReplaceState = window.history.replaceState;

  window.history.pushState = function (...args) {
    originalPushState.apply(this, args);
    if (!isAdmin && hasDebugParam()) {
      console.log("[DEBUG_GUARD] Debug in pushState - blocking");
      clearDebugCookies();
      stripDebugFromUrl();
    }
  };

  window.history.replaceState = function (...args) {
    originalReplaceState.apply(this, args);
    if (!isAdmin && hasDebugParam()) {
      console.log("[DEBUG_GUARD] Debug in replaceState - blocking");
      clearDebugCookies();
      stripDebugFromUrl();
    }
  };

  // Monitor popstate (browser back/forward)
  window.addEventListener("popstate", () => {
    if (!isAdmin && hasDebugParam()) {
      console.log("[DEBUG_GUARD] Debug in popstate - blocking");
      clearDebugCookies();
      stripDebugFromUrl();
    }
  });

  // Periodic check every 500ms
  setInterval(() => {
    if (!isAdmin && (hasDebugParam() || document.cookie.includes("debug"))) {
      clearDebugCookies();
      stripDebugFromUrl();
    }
  }, 500);
}

//  FIXED: Odoo 18 patch syntax
patch(WebClient.prototype, {
  setup() {
    super.setup();

    onWillStart(async () => {
      const isAdmin = await user.hasGroup("base.group_system");

      if (isAdmin) {
        console.log("[DEBUG_GUARD] Admin user - debug mode allowed");
        return;
      }

      // Non-admin: Clean ngay lập tức
      console.log(
        "[DEBUG_GUARD] Non-admin user detected - activating debug blocker"
      );
      clearDebugCookies();
      stripDebugFromUrl();
    });

    onMounted(async () => {
      const isAdmin = await user.hasGroup("base.group_system");
      // Start monitoring sau khi mount
      monitorAndBlockDebug(isAdmin);
    });
  },
});

