/*
 * Catalog price-field sync (Product / Service forms).
 *
 * Keeps the pricing fields consistent as the user types, so what they see is
 * what gets saved — no more "0.0 selling price" in the detail view because a
 * derived field was left blank.
 *
 * Fields are located by data-* hooks set in catalog/forms.py:
 *   [data-price-cost]   Import cost (USD)        (Product only)
 *   [data-price-markup] Markup %                 (Product only)
 *   [data-price-usd]    Selling price (USD)
 *   [data-price-lyd]    Manual LYD price (override) + carries [data-usd-rate]
 * Repeated grids can wrap each group in [data-price-sync-row] so calculations
 * stay inside that row instead of the surrounding form.
 *
 * Sync rules (base = cost):
 *   edit markup  -> usd = cost * (1 + markup/100)
 *   edit usd     -> markup = (usd/cost - 1) * 100
 *   edit cost    -> if manual LYD is set, keep LYD fixed and recompute
 *                   usd + markup; otherwise keep markup and recompute usd.
 *   edit LYD     -> treated as a deliberate override: usd = LYD / rate,
 *                   markup back-computed.
 *
 * The LYD selling price is kept LIVE: while the override field is empty we only
 * show the derived LYD as its *placeholder* (never a real value), so a blank
 * override still means "sell at the live rate". A typed value becomes a real
 * fixed price. The modal executes injected scripts, and event delegation +
 * a MutationObserver make this work for AJAX-loaded modal forms.
 */
(function () {
    "use strict";

    function num(el) {
        if (!el || el.value === "" || el.value == null) return NaN;
        var v = parseFloat(el.value);
        return isNaN(v) ? NaN : v;
    }

    function round2(n) {
        return Math.round((n + Number.EPSILON) * 100) / 100;
    }

    function fields(form) {
        return {
            currency: form.querySelector("[data-product-currency]"),
            cost: form.querySelector("[data-price-cost]"),
            markup: form.querySelector("[data-price-markup]"),
            usd: form.querySelector("[data-price-usd]"),
            lyd: form.querySelector("[data-price-lyd]"),
        };
    }

    function scopeFor(target) {
        return (
            (target.closest && target.closest("[data-price-sync-row]")) ||
            (target.closest && target.closest("form"))
        );
    }

    function rateOf(f) {
        if (!f.lyd) return NaN;
        var rates = f.currency ? JSON.parse(f.currency.getAttribute("data-currency-rates") || "{}") : {};
        var r = parseFloat(f.currency ? rates[f.currency.value] : f.lyd.getAttribute("data-usd-rate"));
        return isNaN(r) || r <= 0 ? NaN : r;
    }

    // Refresh the LYD field's placeholder from the current USD price. Only touch
    // the placeholder while the override is empty, so a real typed value wins.
    function refreshLydPreview(f) {
        if (!f.lyd) return;
        if (f.lyd.value !== "") return; // user set a real override; leave it.
        var rate = rateOf(f);
        var usd = num(f.usd);
        if (isNaN(rate) || isNaN(usd) || usd <= 0) {
            f.lyd.placeholder = "";
            return;
        }
        var lyd = round2(usd * rate);
        f.lyd.placeholder = "≈ " + lyd.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function fromMarkup(f) {
        var cost = num(f.cost), markup = num(f.markup);
        if (f.usd && !isNaN(cost) && !isNaN(markup)) {
            f.usd.value = round2(cost * (1 + markup / 100)).toFixed(2);
        }
        refreshLydPreview(f);
    }

    function fromUsd(f) {
        var cost = num(f.cost), usd = num(f.usd);
        if (f.markup && !isNaN(cost) && cost > 0 && !isNaN(usd)) {
            var markup = round2((usd / cost - 1) * 100);
            if (markup < 0) markup = 0;
            f.markup.value = markup.toFixed(2);
        }
        refreshLydPreview(f);
    }

    function fromCost(f) {
        var cost = num(f.cost), markup = num(f.markup), usd = num(f.usd);
        if (f.lyd && f.lyd.value !== "") {
            fromLyd(f);
            return;
        }
        if (f.usd && !isNaN(cost) && !isNaN(markup)) {
            // Keep the entered markup; the selling price moves with the cost.
            f.usd.value = round2(cost * (1 + markup / 100)).toFixed(2);
        } else if (f.markup && !isNaN(cost) && cost > 0 && !isNaN(usd)) {
            var m = round2((usd / cost - 1) * 100);
            f.markup.value = (m < 0 ? 0 : m).toFixed(2);
        }
        refreshLydPreview(f);
    }

    function fromLyd(f) {
        // A typed override defines the LYD price; back-fill USD and markup so the
        // record stays internally consistent.
        var lyd = num(f.lyd), rate = rateOf(f), cost = num(f.cost);
        if (isNaN(lyd) || isNaN(rate)) return;
        var usd = round2(lyd / rate);
        if (f.usd) f.usd.value = usd.toFixed(2);
        if (f.markup && !isNaN(cost) && cost > 0) {
            var m = round2((usd / cost - 1) * 100);
            f.markup.value = (m < 0 ? 0 : m).toFixed(2);
        }
    }

    function handle(target) {
        var scope = scopeFor(target);
        if (!scope) return;
        var f = fields(scope);
        if (!f.usd && !f.lyd) return; // not a pricing form
        if (target === f.markup) fromMarkup(f);
        else if (target === f.usd) fromUsd(f);
        else if (target === f.cost) fromCost(f);
        else if (target === f.lyd) fromLyd(f);
    }

    document.addEventListener("input", function (e) {
        if (e.target && (e.target.matches("[data-price-cost],[data-price-markup],[data-price-usd],[data-price-lyd]"))) {
            handle(e.target);
        }
    });

    document.addEventListener("change", function (e) {
        if (e.target && e.target.matches("[data-product-currency]")) {
            var scope = scopeFor(e.target);
            if (scope) refreshLydPreview(fields(scope));
        }
    });

    // Seed the LYD placeholder when a pricing form is (re)loaded into a modal.
    function initIn(root) {
        var lydFields = root.querySelectorAll ? root.querySelectorAll("[data-price-lyd]") : [];
        lydFields.forEach(function (lyd) {
            var scope = scopeFor(lyd);
            if (scope) refreshLydPreview(fields(scope));
        });
    }

    new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
            m.addedNodes.forEach(function (node) {
                if (node.nodeType === 1) initIn(node);
            });
        });
    }).observe(document.body, { childList: true, subtree: true });

    initIn(document);
})();
