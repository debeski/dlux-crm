(() => {
  function bindOptionalEnhancements(root = document) {
    root.querySelectorAll("#optional-enhancements-form:not([data-enhancements-bound])").forEach((form) => {
      form.dataset.enhancementsBound = "1";
      // Field names carry a prefix inside dlux's setup wizard and grouped tiles.
      const field = (name) => form.querySelector(`[name="${name}"], [name$="-${name}"]`);
      const master = field("automotive_enabled");
      const criteria = form.querySelector("#automotive-criteria-fields");
      const engine = field("criterion_engine");
      const fuel = field("criterion_fuel_type");
      const preview = form.querySelector("[data-automotive-workflow-preview]");
      const previewOutput = form.querySelector("[data-automotive-workflow-output]");
      const manage = form.querySelector("[data-automotive-manage]");
      const manageHint = form.querySelector("[data-automotive-manage-hint]");
      if (!master || !criteria) return;

      const manageWasEnabled = manage?.dataset.persistedEnabled === "true";
      const syncManage = () => {
        if (!manage) return;
        const canOpen = manageWasEnabled && master.checked;
        manage.classList.toggle("disabled", !canOpen);
        manage.setAttribute("aria-disabled", canOpen ? "false" : "true");
        if (manage.tagName === "A") manage.tabIndex = canOpen ? 0 : -1;
        if (manageHint) manageHint.hidden = !(master.checked && !manageWasEnabled);
      };
      manage?.addEventListener("click", (event) => {
        if (!manageWasEnabled || !master.checked) event.preventDefault();
      });

      const syncPreview = () => {
        if (!preview || !previewOutput) return;
        const steps = [preview.dataset.coreLabel];
        criteria.querySelectorAll(".dlux-settings-toggle-field__input").forEach((input) => {
          if (!input.checked) return;
          const wrapper = input.closest("[data-dlux-settings-toggle-field]");
          const label = wrapper?.querySelector(".dlux-settings-toggle-field__label")?.textContent?.trim();
          if (label) steps.push(label);
        });
        steps.push(preview.dataset.endLabel);
        const arrow = getComputedStyle(previewOutput).direction === "rtl" ? " ← " : " → ";
        previewOutput.textContent = steps.filter(Boolean).join(arrow);
      };
      // Greying the criteria out while the master is off is common/js/dependent_settings.js.
      const syncMaster = () => {
        syncManage();
        syncPreview();
      };
      master.addEventListener("change", syncMaster);
      syncMaster();

      if (engine && fuel) {
        fuel.addEventListener("change", () => {
          if (fuel.checked) engine.checked = true;
          syncPreview();
        });
        engine.addEventListener("change", () => {
          if (!engine.checked) fuel.checked = false;
          syncPreview();
        });
      }
      criteria.addEventListener("change", syncPreview);
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
