/*
 * scoped_crud.js — wire DluxTable row actions on a ScopedListView page to the
 * project's form-only dynamic modals (config.urls: scoped_modal_manager/delete).
 *
 * DluxTable rows dispatch `dlux:record:{view,edit,delete}` (bubbling) from the
 * context menu. Dlux's own fallback (context_menu/js/main.js) would navigate to
 * /{app}/{id}/edit/ — routes that don't exist here. We intercept on the bubbling
 * path (document, before the window-level fallback), call preventDefault() to opt
 * out of that navigation, and instead open the form-only modal via the documented
 * `dlux:dynamic_modal:open` event (or POST for delete).
 */
(function () {
    "use strict";

    function config() {
        return document.querySelector("[data-scoped-crud]");
    }

    function buildUrl(template, id) {
        return template ? template.replace("__pk__", encodeURIComponent(id)) : null;
    }

    function openModal(url, title) {
        document.body.dispatchEvent(
            new CustomEvent("dlux:dynamic_modal:open", {
                detail: { data: { url: url, title: title || "" } },
            })
        );
    }

    function getCookie(name) {
        const match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
        return match ? decodeURIComponent(match.pop()) : "";
    }

    function handleOpen(action) {
        return function (e) {
            const cfg = config();
            const data = e.detail && e.detail.data;
            if (!cfg || !data || !data.id) return;
            // Opt out of the dlux full-page fallback navigation.
            e.preventDefault();
            let url = buildUrl(cfg.getAttribute("data-modal-base-url"), data.id);
            if (!url) return;
            if (action === "view") url += "?action=view";
            openModal(url, data.name);
        };
    }

    function handleDelete(e) {
        const cfg = config();
        const data = e.detail && e.detail.data;
        if (!cfg || !data || !data.id) return;
        e.preventDefault();
        if (!window.confirm("Delete: " + (data.name || data.id) + "?")) return;
        const url = buildUrl(cfg.getAttribute("data-modal-delete-url"), data.id);
        if (!url) return;
        fetch(url, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": getCookie(cfg.getAttribute("data-csrf-cookie") || "csrftoken"),
            },
        })
            .then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json().catch(function () { return {}; });
            })
            .then(function (res) {
                if (res && res.error) {
                    window.alert(res.error);
                    return;
                }
                window.location.reload();
            })
            .catch(function (err) { window.alert(err.message); });
    }

    // Attach on `document` (bubble phase) so we run before the window-level dlux
    // fallback and its defaultPrevented check causes it to bail.
    document.addEventListener("dlux:record:view", handleOpen("view"));
    document.addEventListener("dlux:record:edit", handleOpen("edit"));
    document.addEventListener("dlux:record:delete", handleDelete);
})();
