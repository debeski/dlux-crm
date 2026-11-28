(function () {
    "use strict";

    // The options modal can run this file again; bind the document listeners once.
    if (window.CrmProductsLayoutBound) return;
    window.CrmProductsLayoutBound = true;

    var DEFAULT_NS = "sales_crm.products_layout";

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function appPrefUrl(group, ns) {
        var template = group ? (group.getAttribute("data-app-pref-url-template") || "") : "";
        if (template && template.indexOf("__namespace__") !== -1) {
            return template.replace("__namespace__", encodeURIComponent(ns));
        }
        return "";
    }

    function setGroupDisabled(group, disabled) {
        if (!group) return;
        group.querySelectorAll("[data-products-layout-option]").forEach(function (b) {
            b.disabled = disabled;
        });
    }

    function syncAppPrefCache(ns, value) {
        if (!window.USER_PREFS) return;
        if (!window.USER_PREFS.app || typeof window.USER_PREFS.app !== "object") {
            window.USER_PREFS.app = {};
        }
        if (value === null || value === undefined) delete window.USER_PREFS.app[ns];
        else window.USER_PREFS.app[ns] = value;
    }

    function saveAppPreference(group, ns, value) {
        var url = appPrefUrl(group, ns);
        var token = csrfToken();
        if (url && token) {
            return fetch(url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": token,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(value === undefined ? null : value),
            }).then(function (response) {
                if (!response.ok) {
                    throw new Error("products-layout-preference-save-failed");
                }
                syncAppPrefCache(ns, value);
                return response;
            });
        }

        if (typeof window.updateAppPreference === "function") {
            return window.updateAppPreference(ns, value).then(function (response) {
                if (response && response.ok === false) {
                    throw new Error("products-layout-preference-save-failed");
                }
                syncAppPrefCache(ns, value);
                return response;
            });
        }

        return Promise.reject(new Error("products-layout-preference-url-missing"));
    }

    function setSelectorDisabled(group, disabled) {
        if (!group) return;
        group.querySelectorAll("input.dlux-choice-option__input").forEach(function (i) {
            i.disabled = disabled;
        });
    }

    function commitLayout(group, value, disable, enable, onSuccess) {
        var ns = (group && group.getAttribute("data-products-layout-ns")) || DEFAULT_NS;
        disable();

        saveAppPreference(group, ns, value).then(onSuccess).catch(function (err) {
            enable();
            if (window.console && typeof window.console.error === "function") {
                window.console.error("Failed to save products layout preference.", err);
            }
        });
    }

    document.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-products-layout-option]");
        if (!btn) return;
        e.preventDefault();

        if (btn.getAttribute("aria-pressed") === "true" || btn.classList.contains("btn-primary")) {
            return;
        }

        var group = btn.closest("[data-products-layout-switch]");
        commitLayout(
            group,
            btn.getAttribute("data-products-layout-option"),
            function () { setGroupDisabled(group, true); },
            function () { setGroupDisabled(group, false); },
            function () { window.location.reload(); }
        );
    });

    document.addEventListener("change", function (e) {
        var input = e.target;
        if (!input || !input.matches || !input.matches('input[name="products_layout"].dlux-choice-option__input')) {
            return;
        }
        if (!input.checked) return;

        var group = input.closest("[data-products-layout-switch]");
        commitLayout(
            group,
            input.value,
            function () { setSelectorDisabled(group, true); },
            function () { setSelectorDisabled(group, false); },
            function () {
                setSelectorDisabled(group, false);
                var msg = group && group.getAttribute("data-saved-message");
                if (msg && typeof window.showToast === "function") {
                    window.showToast(msg);
                }
            }
        );
    });
})();
