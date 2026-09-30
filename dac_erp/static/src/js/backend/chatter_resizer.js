(function () {
  "use strict";

  const STORAGE_KEY = "dac_chatter_width";
  let isDragging = false;

  function initResizer() {
    const formView = document.querySelector(".o_form_view");
    if (!formView) return;

    // Find the sheet background and the chatter container
    const sheetBg = formView.querySelector(".o_form_sheet_bg");
    
    // Check multiple potential class names for chatter to ensure maximum compatibility
    const chatter = formView.querySelector(
      ".o_FormRenderer_chatterContainer, .o-mail-Chatter, .o_chatter, .o_form_view_chatter"
    );

    if (!sheetBg || !chatter) return;

    // Apply the saved width on initial render
    applySavedWidth(chatter);

    // Check if resizer is already injected
    let resizer = formView.querySelector(".dac-chatter-resizer");
    if (resizer) {
      return;
    }

    // Create and insert the resizer splitter
    resizer = document.createElement("div");
    resizer.className = "dac-chatter-resizer";
    
    // Insert resizer right before the chatter container so it sits between sheetBg and chatter
    chatter.parentNode.insertBefore(resizer, chatter);

    // Add dragging event listeners
    resizer.addEventListener("mousedown", function (e) {
      // Only handle left clicks
      if (e.button !== 0) return;

      // Verify resizer is visible (not hidden by media query or display none)
      const resizerStyle = window.getComputedStyle(resizer);
      if (resizerStyle.display === "none") return;

      e.preventDefault();
      isDragging = true;
      resizer.classList.add("is-dragging");
      document.body.classList.add("dac-resizing-chatter");

      const initialX = e.clientX;
      const initialWidth = chatter.getBoundingClientRect().width;
      const formWidth = formView.getBoundingClientRect().width;

      function onMouseMove(e) {
        if (!isDragging) return;

        // Since chatter is on the right, dragging left (negative dx) increases chatter width
        const dx = initialX - e.clientX;
        let newWidth = initialWidth + dx;

        // Constrain chatter width (min 260px, max 60% of form width)
        const minWidth = 260;
        const maxWidth = formWidth * 0.6;
        if (newWidth < minWidth) newWidth = minWidth;
        if (newWidth > maxWidth) newWidth = maxWidth;

        // Set styles with !important to override Odoo defaults
        setChatterWidth(chatter, newWidth);
      }

      function onMouseUp() {
        if (isDragging) {
          isDragging = false;
          resizer.classList.remove("is-dragging");
          document.body.classList.remove("dac-resizing-chatter");

          // Save final width to localStorage
          const finalWidth = chatter.getBoundingClientRect().width;
          localStorage.setItem(STORAGE_KEY, finalWidth);
        }

        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      }

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  }

  function setChatterWidth(chatter, width) {
    const widthStr = typeof width === "number" ? `${width}px` : width;
    chatter.style.setProperty("width", widthStr, "important");
    chatter.style.setProperty("flex", `0 0 ${widthStr}`, "important");
    chatter.style.setProperty("min-width", widthStr, "important");
    chatter.style.setProperty("max-width", widthStr, "important");
  }

  function applySavedWidth(chatter) {
    // Only apply if resizer is visible (i.e. in 2-column layout)
    const formView = chatter.closest(".o_form_view");
    if (!formView) return;
    
    // Check if the viewport width supports 2-column mode (min-width: 992px)
    if (window.innerWidth < 992) {
      // Clear any custom width overrides when in mobile/single column mode
      chatter.style.removeProperty("width");
      chatter.style.removeProperty("flex");
      chatter.style.removeProperty("min-width");
      chatter.style.removeProperty("max-width");
      return;
    }

    const savedWidth = localStorage.getItem(STORAGE_KEY);
    if (savedWidth) {
      setChatterWidth(chatter, `${savedWidth}px`);
    }
  }

  // Set up MutationObserver to handle dynamic page changes
  const observer = new MutationObserver(function () {
    initResizer();
  });

  // Start observing
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
    // Also try running immediately
    initResizer();
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      observer.observe(document.body, { childList: true, subtree: true });
      initResizer();
    });
  }

  // Handle window resizing (e.g. going from wide screen to narrow screen)
  window.addEventListener("resize", function () {
    const chatter = document.querySelector(
      ".o_FormRenderer_chatterContainer, .o-mail-Chatter, .o_chatter, .o_form_view_chatter"
    );
    if (chatter) {
      applySavedWidth(chatter);
    }
  });
})();
