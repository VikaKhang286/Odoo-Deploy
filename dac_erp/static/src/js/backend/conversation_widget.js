/** @odoo-module **/

// ===================================================================
// DAC ERP - Conversation Widget với Drag & Drop + Bubble Mode
// File: conversation_widget.js
// Description: Widget có thể kéo thả và chuyển đổi bubble mode
// ===================================================================

// Widget state
let isCollapsed = true;
let isBubbleMode = false;
let isDragging = false;
let dragOffset = { x: 0, y: 0 };

// Initialize all functionality
function initConversationWidget() {
  setupToggle();
  setupBubbleMode();
  setupDragAndDrop();
  setupResponsiveHandling();
  loadWidgetPosition();
  // console.log(
  //   "Conversation Widget fully initialized with drag & bubble features"
  // );
}

// Setup toggle functionality (existing)
function setupToggle() {
  const toggleIcon = document.querySelector(".conversation-toggle");
  const content = document.querySelector(".conversation-content");

  if (!toggleIcon || !content) {
    return false;
  }

  toggleIcon.removeEventListener("click", handleToggle);
  toggleIcon.addEventListener("click", handleToggle);

  // Set initial state
  if (isCollapsed) {
    content.style.display = "none";
    toggleIcon.style.transform = "rotate(180deg)";
  } else {
    content.style.display = "block";
    toggleIcon.style.transform = "rotate(0deg)";
  }

  return true;
}

// Handle toggle click (existing)
function handleToggle(e) {
  e.preventDefault();
  e.stopPropagation();

  const content = document.querySelector(".conversation-content");
  const toggleIcon = document.querySelector(".conversation-toggle");

  if (!content || !toggleIcon) return;

  isCollapsed = !isCollapsed;

  if (isCollapsed) {
    content.style.display = "none";
    toggleIcon.style.transform = "rotate(180deg)";
  } else {
    content.style.display = "block";
    toggleIcon.style.transform = "rotate(0deg)";
  }
}

// NEW: Setup bubble mode functionality
function setupBubbleMode() {
  const bubbleToggleBtn = document.querySelector(".bubble-toggle-btn");
  const bubbleToggle = document.querySelector(".bubble-toggle");
  const widget = document.querySelector(".conversation-widget");
  const container = document.querySelector(".conversation-widget-container");

  if (!bubbleToggleBtn || !widget || !container) return;

  // Button to switch to bubble mode
  bubbleToggleBtn.removeEventListener("click", switchToBubbleMode);
  bubbleToggleBtn.addEventListener("click", switchToBubbleMode);

  // Bubble toggle to switch back to normal mode
  if (bubbleToggle) {
    bubbleToggle.removeEventListener("click", switchToNormalMode);
    bubbleToggle.addEventListener("click", switchToNormalMode);
  }

  // Click on bubble to expand
  widget.removeEventListener("click", handleBubbleClick);
  widget.addEventListener("click", handleBubbleClick);
}

// Switch to bubble mode
function switchToBubbleMode(e) {
  e.preventDefault();
  e.stopPropagation();

  const widget = document.querySelector(".conversation-widget");
  const container = document.querySelector(".conversation-widget-container");
  const bubbleNotification = document.querySelector(".bubble-notification");
  const bubbleToggle = document.querySelector(".bubble-toggle");

  if (!widget || !container) return;

  isBubbleMode = true;
  widget.classList.add("bubble-mode");
  container.classList.add("bubble-mode");

  // Show bubble elements
  if (bubbleNotification) bubbleNotification.style.display = "block";
  if (bubbleToggle) bubbleToggle.style.display = "flex";

  // Save state
  localStorage.setItem("conversation_widget_bubble_mode", "true");

  console.log("Switched to bubble mode");
}

// Switch to normal mode
function switchToNormalMode(e) {
  e.preventDefault();
  e.stopPropagation();

  const widget = document.querySelector(".conversation-widget");
  const container = document.querySelector(".conversation-widget-container");
  const bubbleNotification = document.querySelector(".bubble-notification");
  const bubbleToggle = document.querySelector(".bubble-toggle");

  if (!widget || !container) return;

  isBubbleMode = false;
  widget.classList.remove("bubble-mode");
  container.classList.remove("bubble-mode");

  // Hide bubble elements
  if (bubbleNotification) bubbleNotification.style.display = "none";
  if (bubbleToggle) bubbleToggle.style.display = "none";

  // Save state
  localStorage.setItem("conversation_widget_bubble_mode", "false");

  console.log("Switched to normal mode");
}

// Handle bubble click (expand to normal mode)
function handleBubbleClick(e) {
  if (isBubbleMode && !e.target.closest(".bubble-toggle")) {
    switchToNormalMode(e);
  }
}

// NEW: Setup drag and drop functionality
function setupDragAndDrop() {
  const container = document.querySelector(".conversation-widget-container");
  const header = document.querySelector(".conversation-header");

  if (!container || !header) return;

  // Make container draggable
  header.removeEventListener("mousedown", startDrag);
  header.addEventListener("mousedown", startDrag);
  document.removeEventListener("mousemove", handleDrag);
  document.addEventListener("mousemove", handleDrag);
  document.removeEventListener("mouseup", endDrag);
  document.addEventListener("mouseup", endDrag);

  // Touch events for mobile
  header.removeEventListener("touchstart", startDrag);
  header.addEventListener("touchstart", startDrag);
  document.removeEventListener("touchmove", handleDrag);
  document.addEventListener("touchmove", handleDrag);
  document.removeEventListener("touchend", endDrag);
  document.addEventListener("touchend", endDrag);
}

// Start dragging
function startDrag(e) {
  // Don't drag if clicking on toggle buttons
  if (
    e.target.closest(".conversation-toggle") ||
    e.target.closest(".bubble-toggle-btn") ||
    isBubbleMode
  ) {
    return;
  }

  e.preventDefault();
  isDragging = true;

  const container = document.querySelector(".conversation-widget-container");
  const widget = document.querySelector(".conversation-widget");

  if (!container || !widget) return;

  // Get mouse/touch position
  const clientX = e.clientX || (e.touches && e.touches[0].clientX);
  const clientY = e.clientY || (e.touches && e.touches[0].clientY);

  // Calculate offset from container's top-left corner
  const rect = container.getBoundingClientRect();
  dragOffset.x = clientX - rect.left;
  dragOffset.y = clientY - rect.top;

  // Add dragging classes
  container.classList.add("is-dragging");
  widget.classList.add("dragging");
  document.body.style.cursor = "grabbing";
  document.body.style.userSelect = "none";

  console.log("Started dragging widget");
}

// Handle dragging
function handleDrag(e) {
  if (!isDragging) return;

  e.preventDefault();

  const container = document.querySelector(".conversation-widget-container");
  if (!container) return;

  // Get mouse/touch position
  const clientX = e.clientX || (e.touches && e.touches[0].clientX);
  const clientY = e.clientY || (e.touches && e.touches[0].clientY);

  // Calculate new position
  let newX = clientX - dragOffset.x;
  let newY = clientY - dragOffset.y;

  // Keep widget within viewport bounds
  const maxX = window.innerWidth - container.offsetWidth;
  const maxY = window.innerHeight - container.offsetHeight;

  newX = Math.max(0, Math.min(newX, maxX));
  newY = Math.max(0, Math.min(newY, maxY));

  // Update position
  container.style.left = newX + "px";
  container.style.top = newY + "px";
  container.style.right = "auto"; // Remove right positioning
}

// End dragging
function endDrag(e) {
  if (!isDragging) return;

  isDragging = false;

  const container = document.querySelector(".conversation-widget-container");
  const widget = document.querySelector(".conversation-widget");

  if (container && widget) {
    container.classList.remove("is-dragging");
    widget.classList.remove("dragging");

    // Save position
    saveWidgetPosition();
  }

  document.body.style.cursor = "";
  document.body.style.userSelect = "";

  console.log("Stopped dragging widget");
}

// Save widget position to localStorage
function saveWidgetPosition() {
  const container = document.querySelector(".conversation-widget-container");
  if (!container) return;

  const position = {
    left: container.style.left,
    top: container.style.top,
    right: container.style.right,
  };

  localStorage.setItem(
    "conversation_widget_position",
    JSON.stringify(position)
  );
}

// Load widget position from localStorage
function loadWidgetPosition() {
  const container = document.querySelector(".conversation-widget-container");
  if (!container) return;

  // Load position
  const savedPosition = localStorage.getItem("conversation_widget_position");
  if (savedPosition) {
    try {
      const position = JSON.parse(savedPosition);
      if (position.left) container.style.left = position.left;
      if (position.top) container.style.top = position.top;
      if (position.left) container.style.right = "auto"; // Remove right when left is set
    } catch (e) {
      console.warn("Could not load widget position:", e);
    }
  }

  // Load bubble mode state
  const savedBubbleMode = localStorage.getItem(
    "conversation_widget_bubble_mode"
  );
  if (savedBubbleMode === "true") {
    setTimeout(() => {
      const event = { preventDefault: () => {}, stopPropagation: () => {} };
      switchToBubbleMode(event);
    }, 100);
  }
}

// Responsive handling (updated)
function handleResponsiveConversationWidget() {
  const conversationWidget = document.querySelector(
    ".conversation-widget-container"
  );

  if (!conversationWidget) return;

  if (window.innerWidth <= 768) {
    // On mobile, reset to default position
    conversationWidget.style.position = "relative";
    conversationWidget.style.top = "auto";
    conversationWidget.style.left = "auto";
    conversationWidget.style.right = "auto";

    // Move to bottom of the Odoo form sheet on compact screens.
    const sheet = document.querySelector(".dac-sale-form .o_form_sheet, .o_form_sheet");
    if (sheet && conversationWidget.parentNode !== sheet) {
      sheet.appendChild(conversationWidget);
    }
  } else {
    // On desktop, restore fixed positioning
    conversationWidget.style.position = "fixed";

    // Move back to form
    const form = document.querySelector(".dac-sale-form");
    if (form && conversationWidget.parentNode !== form) {
      form.appendChild(conversationWidget);
    }

    // Restore saved position
    loadWidgetPosition();
  }
}

// Setup responsive handling
function setupResponsiveHandling() {
  window.removeEventListener("resize", handleResponsiveConversationWidget);
  window.addEventListener("resize", handleResponsiveConversationWidget);
  handleResponsiveConversationWidget(); // Initial check
}

// Observe DOM changes
function observeWidget() {
  const target = document.body;
  const observer = new MutationObserver(() => {
    initConversationWidget();
  });
  observer.observe(target, { childList: true, subtree: true });
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  initConversationWidget();
  observeWidget();
});

// Also try when page changes (for Odoo SPA navigation)
if (typeof window !== "undefined") {
  window.addEventListener("load", () => {
    setTimeout(() => {
      initConversationWidget();
    }, 500);
  });

  window.addEventListener("hashchange", () => {
    setTimeout(() => {
      initConversationWidget();
    }, 1000);
  });
}
