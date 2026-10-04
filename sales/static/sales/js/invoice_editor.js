(function () {
    "use strict";

    function ready(fn) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }

    ready(function () {
        var root = document.querySelector("[data-invoice-catalog]");
        var mapEl = document.getElementById("catalog-map");
        if (!root || !mapEl) return;

        var catalog = {};
        try { catalog = JSON.parse(mapEl.textContent || "{}"); } catch (e) { catalog = {}; }
        var products = catalog.products || [];
        var services = catalog.services || [];

        var S = {
            perJob: root.dataset.strPerjob || "Per job",
            onlyLeft: root.dataset.strOnlyleft || "Only {n} in stock",
            items: root.dataset.strItems || "{n} item(s)",
        };

        var grid = root.querySelector("[data-picker-grid]");
        var emptyMsg = root.querySelector("[data-picker-empty]");
        var searchInput = root.querySelector("[data-picker-search]");
        var categorySel = root.querySelector("[data-picker-category]");
        var modeSwitch = root.querySelector("[data-picker-mode-switch]");
        var customBtn = root.querySelector("[data-add-custom-line]");

        var cartBody = document.querySelector("[data-cart-body]");
        var cartEmpty = document.querySelector("[data-cart-empty]");
        var cartCount = document.querySelector("[data-cart-count]");
        var subtotalCell = document.getElementById("subtotal-cell");
        var tpl = document.getElementById("empty-cart-row");
        var totalForms = document.querySelector('input[name$="-TOTAL_FORMS"]');

        var mode = "products";
        var fmt = function (n) {
            return (isNaN(n) ? 0 : n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };
        var esc = function (s) {
            var d = document.createElement("div");
            d.textContent = s == null ? "" : String(s);
            return d.innerHTML;
        };
        var num = function (v) { return v === "" || v == null ? "" : String(v); };

        // ---- Picker rendering --------------------------------------------- //
        function swatch(hex) {
            return '<span class="picker-chip__swatch" style="background:' + esc(hex || "#ccc") + '"></span>';
        }

        function productTile(p) {
            var tile = document.createElement("div");
            tile.className = "picker-tile";
            var media = p.image
                ? '<span class="picker-tile__media"><img src="' + esc(p.image) + '" alt=""></span>'
                : '<span class="picker-tile__media"><i class="bi bi-box-seam"></i></span>';
            var variantsHtml;
            if (p.variants && p.variants.length) {
                variantsHtml = p.variants.map(function (v) {
                    var label = v.size || v.color_label || "—";
                    var low = v.stock_qty <= 3;
                    return '<button type="button" class="picker-chip' + (low ? " is-low" : "") + '"'
                        + ' data-add-variant data-vid="' + v.id + '">'
                        + (v.color ? swatch(v.color_hex) : "")
                        + '<span>' + esc(label) + '</span>'
                        + '<span class="picker-chip__qty">' + fmt(v.stock_qty) + '</span></button>';
                }).join("");
            } else {
                variantsHtml = '<button type="button" class="picker-add" data-add-variant><i class="bi bi-plus-lg"></i></button>';
            }
            tile.innerHTML = media
                + '<div class="picker-tile__name">' + esc(p.name) + '</div>'
                + '<div class="picker-tile__price"><b>' + fmt(p.price) + '</b> LYD</div>'
                + '<div class="picker-tile__variants">' + variantsHtml + '</div>';
            tile.querySelectorAll("[data-add-variant]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var v = null;
                    if (btn.dataset.vid) v = (p.variants || []).find(function (x) { return String(x.id) === btn.dataset.vid; });
                    addProductRow(p, v);
                });
            });
            return tile;
        }

        function serviceTile(s) {
            var tile = document.createElement("div");
            tile.className = "picker-tile";
            var media = s.image
                ? '<span class="picker-tile__media"><img src="' + esc(s.image) + '" alt=""></span>'
                : '<span class="picker-tile__media"><i class="bi ' + esc(s.icon || "bi-tools") + '"></i></span>';
            var price = s.price == null ? esc(S.perJob) : "<b>" + fmt(s.price) + "</b> LYD";
            tile.innerHTML = media
                + '<div class="picker-tile__name">' + esc(s.name) + '</div>'
                + '<div class="picker-tile__price">' + price + '</div>'
                + '<div class="picker-tile__variants"><button type="button" class="picker-add" data-add-service><i class="bi bi-plus-lg"></i></button></div>';
            tile.querySelector("[data-add-service]").addEventListener("click", function () { addServiceRow(s); });
            return tile;
        }

        function renderPicker() {
            if (!grid) return;
            grid.innerHTML = "";
            var term = (searchInput && searchInput.value || "").trim().toLowerCase();
            var cat = categorySel ? categorySel.value : "";
            var list = mode === "products" ? products : services;
            var shown = 0;
            list.forEach(function (item) {
                if (mode === "products") {
                    if (cat && String(item.category_id) !== String(cat)) return;
                    if (term && item.name.toLowerCase().indexOf(term) === -1 && (item.alias || "").toLowerCase().indexOf(term) === -1
                        && (item.category || "").toLowerCase().indexOf(term) === -1) return;
                    grid.appendChild(productTile(item));
                } else {
                    if (term && item.name.toLowerCase().indexOf(term) === -1
                        && (item.type_label || "").toLowerCase().indexOf(term) === -1) return;
                    grid.appendChild(serviceTile(item));
                }
                shown++;
            });
            if (emptyMsg) emptyMsg.classList.toggle("d-none", shown > 0);
            if (categorySel) categorySel.classList.toggle("d-none", mode !== "products");
        }

        // ---- Cart rows ---------------------------------------------------- //
        function field(row, suffix) { return row.querySelector('[name$="-' + suffix + '"]'); }
        function setField(row, suffix, value) {
            var el = field(row, suffix);
            if (el) el.value = value == null ? "" : value;
            return el;
        }

        function newRow() {
            var idx = parseInt(totalForms.value, 10);
            var html = tpl.innerHTML.replace(/__prefix__/g, idx);
            var holder = document.createElement("div");
            holder.innerHTML = html.trim();
            var row = holder.querySelector("[data-cart-row]");
            totalForms.value = idx + 1;
            return row;
        }

        function attachRow(row) {
            cartBody.appendChild(row);
            wireRow(row);
            recalcAll();
        }

        function addProductRow(p, v) {
            var row = newRow();
            setField(row, "kind", "product");
            setField(row, "product", p.id);
            setField(row, "service", "");
            setField(row, "variant", v ? v.id : "");
            setField(row, "color", v ? v.color : "");
            setField(row, "size", v ? v.size : "");
            setField(row, "description", p.name);
            setField(row, "unit_price_lyd", p.price || 0);
            setField(row, "quantity", 1);
            row.dataset.kind = "product";
            row.dataset.variantStock = v ? num(v.stock_qty) : (p.track_stock ? num(p.stock_qty) : "");
            row.querySelector("[data-cart-label]").textContent = p.name;
            row.querySelector("[data-cart-meta]").textContent = v ? [v.color_label, v.size].filter(Boolean).join(" · ") : "";
            row.querySelector("[data-cart-thumb]").innerHTML = v && v.color
                ? '<span class="cart-swatch" style="background:' + esc(v.color_hex) + '"></span>'
                : '<i class="bi bi-box-seam"></i>';
            attachRow(row);
        }

        function addServiceRow(s) {
            var row = newRow();
            setField(row, "kind", "service");
            setField(row, "service", s.id);
            setField(row, "product", "");
            setField(row, "variant", "");
            setField(row, "color", "");
            setField(row, "size", "");
            setField(row, "description", s.name);
            setField(row, "unit_price_lyd", s.price == null ? 0 : s.price);
            setField(row, "quantity", 1);
            row.dataset.kind = "service";
            row.dataset.variantStock = "";
            row.querySelector("[data-cart-label]").textContent = s.name;
            row.querySelector("[data-cart-meta]").textContent = s.type_label || "";
            row.querySelector("[data-cart-thumb]").innerHTML = '<i class="bi ' + esc(s.icon || "bi-tools") + '"></i>';
            attachRow(row);
        }

        function addCustomRow() {
            var row = newRow();
            setField(row, "kind", "custom");
            setField(row, "product", "");
            setField(row, "service", "");
            setField(row, "variant", "");
            setField(row, "color", "");
            setField(row, "size", "");
            setField(row, "unit_price_lyd", 0);
            setField(row, "quantity", 1);
            row.dataset.kind = "custom";
            row.dataset.variantStock = "";
            row.querySelector("[data-cart-thumb]").innerHTML = '<i class="bi bi-pencil"></i>';
            showCustom(row);
            attachRow(row);
            var desc = row.querySelector(".cart-desc");
            if (desc) desc.focus();
        }

        function showCustom(row) {
            var label = row.querySelector("[data-cart-label]");
            var desc = row.querySelector(".cart-desc");
            if (label) label.classList.add("d-none");
            if (desc) desc.classList.remove("d-none");
        }

        function isActive(row) { return !row.classList.contains("d-none"); }

        function recalcRow(row) {
            if (!isActive(row)) return 0;
            var price = parseFloat(field(row, "unit_price_lyd") && field(row, "unit_price_lyd").value) || 0;
            var qty = parseFloat(field(row, "quantity") && field(row, "quantity").value) || 0;
            var cell = row.querySelector("[data-cart-total]");
            if (cell) cell.textContent = fmt(price * qty);
            var stock = row.dataset.variantStock;
            var qtyEl = field(row, "quantity");
            var meta = row.querySelector("[data-cart-meta]");
            if (stock !== "" && stock != null && qty > parseFloat(stock)) {
                if (qtyEl) qtyEl.classList.add("is-invalid");
                if (meta) { meta.classList.add("is-warn"); meta.textContent = S.onlyLeft.replace("{n}", fmt(parseFloat(stock))); }
            } else {
                if (qtyEl) qtyEl.classList.remove("is-invalid");
                if (meta) meta.classList.remove("is-warn");
            }
            return price * qty;
        }

        function recalcAll() {
            var subtotal = 0;
            var count = 0;
            cartBody.querySelectorAll("[data-cart-row]").forEach(function (row) {
                if (!isActive(row)) return;
                subtotal += recalcRow(row);
                count++;
            });
            if (subtotalCell) subtotalCell.textContent = fmt(subtotal);
            if (cartCount) cartCount.textContent = count ? S.items.replace("{n}", count) : "";
            if (cartEmpty) cartEmpty.classList.toggle("d-none", count > 0);
        }

        function removeRow(row) {
            var del = field(row, "DELETE");
            if (del) {
                del.checked = true;
                row.classList.add("d-none");
                row.querySelectorAll("input").forEach(function (input) {
                    if (input !== del && !input.name.endsWith("-id")) input.disabled = true;
                });
            }
            recalcAll();
        }

        function wireRow(row) {
            var price = field(row, "unit_price_lyd");
            var qty = field(row, "quantity");
            if (price) price.addEventListener("input", recalcAll);
            if (qty) qty.addEventListener("input", recalcAll);
            var rm = row.querySelector("[data-cart-remove]");
            if (rm) rm.addEventListener("click", function () { removeRow(row); });
            if (row.dataset.kind === "custom") showCustom(row);
            var del = field(row, "DELETE");
            if (del && del.checked) removeRow(row);
        }

        // ---- Wire controls ------------------------------------------------ //
        if (modeSwitch) {
            modeSwitch.querySelectorAll("[data-picker-mode]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    mode = btn.dataset.pickerMode;
                    modeSwitch.querySelectorAll("[data-picker-mode]").forEach(function (b) {
                        var on = b === btn;
                        b.classList.toggle("btn-primary", on);
                        b.classList.toggle("btn-outline-secondary", !on);
                    });
                    renderPicker();
                });
            });
        }
        if (searchInput) searchInput.addEventListener("input", renderPicker);
        if (categorySel) categorySel.addEventListener("change", renderPicker);
        if (customBtn) customBtn.addEventListener("click", addCustomRow);

        cartBody.querySelectorAll("[data-cart-row]").forEach(wireRow);
        renderPicker();
        recalcAll();
    });
})();
