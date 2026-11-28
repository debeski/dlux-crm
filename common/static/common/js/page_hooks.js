(function () {
    "use strict";
    // Markup hooks that replace inline handlers and style="" attributes, which
    // the CSP (script-src without 'unsafe-inline', style-src 'self') refuses.
    //   [data-print-page]            click prints the page
    //   form[data-confirm]           submit asks first
    //   [data-submit-on-change]      change submits the field's form
    //   [data-swatch]                background colour ([data-swatch-border]: border colour)
    //   [data-progress]              width, in percent
    //   [data-css-vars]              JSON object of custom properties ("--name")
    // Styles are set through the CSSOM, which style-src does not govern.
    if (window.CrmPageHooks) return;

    function applyStyles(root) {
        if (!root || !root.querySelectorAll) return;
        var nodes = Array.prototype.slice.call(root.querySelectorAll("[data-swatch],[data-progress],[data-css-vars]"));
        if (root.matches && root.matches("[data-swatch],[data-progress],[data-css-vars]")) nodes.unshift(root);
        nodes.forEach(function (el) {
            if (el.hasAttribute("data-swatch")) {
                el.style.background = el.getAttribute("data-swatch");
                if (el.hasAttribute("data-swatch-border")) el.style.borderColor = el.getAttribute("data-swatch-border");
            }
            if (el.hasAttribute("data-progress")) {
                var pct = Math.max(0, Math.min(100, parseFloat(el.getAttribute("data-progress")) || 0));
                el.style.width = pct + "%";
            }
            if (el.hasAttribute("data-css-vars")) {
                var vars = {};
                try { vars = JSON.parse(el.getAttribute("data-css-vars")) || {}; } catch (e) { vars = {}; }
                Object.keys(vars).forEach(function (name) {
                    if (name.indexOf("--") === 0) el.style.setProperty(name, String(vars[name]));
                });
            }
        });
    }

    document.addEventListener("click", function (event) {
        if (event.target.closest && event.target.closest("[data-print-page]")) {
            event.preventDefault();
            window.print();
        }
    });

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm")) return;
        if (!window.confirm(form.getAttribute("data-confirm"))) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener("change", function (event) {
        var field = event.target;
        if (field && field.hasAttribute && field.hasAttribute("data-submit-on-change") && field.form) {
            field.form.submit();
        }
    });

    applyStyles(document);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { applyStyles(document); });
    }
    if (window.MutationObserver) {
        new MutationObserver(function (records) {
            records.forEach(function (record) {
                if (record.type === "attributes") { applyStyles(record.target); return; }
                record.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) applyStyles(node);
                });
            });
        }).observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["data-swatch", "data-swatch-border", "data-progress", "data-css-vars"],
        });
    }

    window.CrmPageHooks = { applyStyles: applyStyles };
})();
