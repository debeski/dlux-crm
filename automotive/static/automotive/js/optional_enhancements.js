(() => {
  function bindOptionalEnhancements(root = document) {
    root.querySelectorAll("#optional-enhancements-form:not([data-enhancements-bound])").forEach((form) => {
      form.dataset.enhancementsBound = "1";
      // Field names carry a prefix inside dlux's setup wizard and grouped tiles.
      const field = (name) => form.querySelector(`[name="${name}"], [name$="-${name}"]`);
      ["automotive", "machinery"].forEach((pack) => {
        const toggle = field(`${pack}_enabled`);
        const manage = form.querySelector(`[data-${pack}-manage]`);
        const hint = form.querySelector(`[data-${pack}-manage-hint]`);
        const persistedEnabled = manage?.dataset.persistedEnabled === "true";
        const sync = () => {
          if (!manage || !toggle) return;
          const canOpen = persistedEnabled && toggle.checked;
          manage.classList.toggle("disabled", !canOpen);
          manage.setAttribute("aria-disabled", canOpen ? "false" : "true");
          if (manage.tagName === "A") manage.tabIndex = canOpen ? 0 : -1;
          if (hint) hint.hidden = !(toggle.checked && !persistedEnabled);
        };
        manage?.addEventListener("click", (event) => {
          if (!persistedEnabled || !toggle?.checked) event.preventDefault();
        });
        toggle?.addEventListener("change", sync);
        sync();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => bindOptionalEnhancements());
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) bindOptionalEnhancements(node);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
