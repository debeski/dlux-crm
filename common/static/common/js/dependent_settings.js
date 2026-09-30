/*
 * Dependent settings blocks (see common/settings_forms.py): greyed out, with
 * dlux's tooltip naming the toggle that unlocks them, while that toggle is off.
 * Settings modals are injected after load, so new blocks are bound on arrival.
 */
(() => {
  function sync(block, master) {
    const on = master.checked;
    block.classList.add("dlux-dependent-settings");
    block.classList.toggle("is-disabled", !on);
    block.setAttribute("aria-disabled", on ? "false" : "true");
    if (on) block.removeAttribute("data-dlux-tooltip");
    else block.setAttribute("data-dlux-tooltip", block.dataset.settingsLockReason || "");
    block.querySelectorAll("input, select, textarea, button").forEach((control) => {
      control.disabled = !on;
      if (on) control.removeAttribute("aria-disabled");
      else control.setAttribute("aria-disabled", "true");
    });
    block.querySelectorAll("[data-dlux-selector]").forEach((selector) => {
      selector.classList.toggle("is-disabled", !on);
      selector.setAttribute("aria-disabled", on ? "false" : "true");
    });
  }

  function bind(root = document) {
    root.querySelectorAll("[data-settings-depends-on]:not([data-settings-bound])").forEach((block) => {
      const scope = block.closest("form") || document;
      const master = scope.querySelector(`input[name="${CSS.escape(block.dataset.settingsDependsOn)}"]`);
      if (!master) return;
      block.dataset.settingsBound = "1";
      master.addEventListener("change", () => sync(block, master));
      sync(block, master);
    });
  }

  document.addEventListener("DOMContentLoaded", () => bind());
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) bind(node);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
