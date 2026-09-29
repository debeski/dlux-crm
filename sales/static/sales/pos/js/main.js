/*
 * Point-of-sale till.
 *
 * The cart lives in localStorage (per user) so a reload — including the one
 * after quick-adding an unknown barcode — keeps the sale. Checkout sends the
 * whole cart once with an idempotency key; the server re-prices, enforces the
 * discount limit, issues the invoice and records payments.
 */
(function () {
    "use strict";

    const setup = JSON.parse(document.getElementById("pos-setup").textContent || "{}");
    const S = setup.strings || {};
    const root = document.querySelector("[data-pos]");
    if (!root) return;

    const $ = (selector, scope) => (scope || document).querySelector(selector);
    const search = $("#pos-search");
    const results = $("[data-pos-results]");
    const linesBox = $("[data-pos-lines]");
    const notice = $("[data-pos-notice]");
    const unknown = $("[data-pos-unknown]");
    const payDialog = $("[data-pos-pay-dialog]");
    const doneDialog = $("[data-pos-done]");
    const storeKey = "pos.cart.v1." + (setup.till || "till");
    const pendingKey = storeKey + ".pending";

    const money = (value) => (Math.round((Number(value) || 0) * 100) / 100).toFixed(2);
    const num = (value) => {
        const parsed = parseFloat(String(value).replace(",", "."));
        return Number.isFinite(parsed) ? parsed : 0;
    };

    function newKey() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return String(Date.now()) + Math.random().toString(16).slice(2);
    }

    function blankCart() {
        return {lines: [], discount: {type: "amount", value: 0}, customer: {name: "", phone: ""}, key: newKey()};
    }

    function loadCart() {
        try {
            const data = JSON.parse(localStorage.getItem(storeKey) || "null");
            if (data && Array.isArray(data.lines)) return Object.assign(blankCart(), data);
        } catch (error) { /* storage blocked or corrupt: start clean */ }
        return blankCart();
    }

    let cart = loadCart();

    function save() {
        try { localStorage.setItem(storeKey, JSON.stringify(cart)); } catch (error) { /* ignore */ }
    }

    function getJSON(url) {
        return fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}})
            .then((response) => {
                if (!response.ok) throw new Error("HTTP " + response.status);
                return response.json();
            });
    }

    function csrf() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (match) return decodeURIComponent(match[1]);
        const input = document.querySelector("input[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function beep() {
        try {
            const context = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = context.createOscillator();
            oscillator.frequency.value = 1200;
            oscillator.connect(context.destination);
            oscillator.start();
            oscillator.stop(context.currentTime + 0.08);
        } catch (error) { /* audio unavailable */ }
        if (navigator.vibrate) navigator.vibrate(40);
    }

    function flash(text, tone) {
        notice.textContent = text;
        notice.className = "pos-notice pos-notice--" + (tone || "info");
        notice.hidden = false;
        clearTimeout(flash.timer);
        flash.timer = setTimeout(() => { notice.hidden = true; }, 2600);
    }

    // ---- totals -------------------------------------------------------
    function lineTotal(line) { return num(line.unit != null ? line.unit : line.price) * num(line.qty); }

    function totals() {
        const subtotal = cart.lines.reduce((sum, line) => sum + lineTotal(line), 0);
        const listTotal = cart.lines.reduce((sum, line) => sum + num(line.price) * num(line.qty), 0);
        let discount = cart.discount.type === "percent"
            ? subtotal * num(cart.discount.value) / 100
            : num(cart.discount.value);
        discount = Math.min(Math.max(discount, 0), subtotal);
        const total = Math.max(subtotal - discount, 0);
        return {subtotal, discount, total, listTotal, given: listTotal - total};
    }

    // ---- cart rendering ----------------------------------------------
    function render() {
        linesBox.replaceChildren();
        cart.lines.forEach((line, index) => {
            const item = document.createElement("li");
            item.className = "pos-line";
            const discounted = line.unit != null && num(line.unit) < num(line.price);
            const stockWarn = line.track && num(line.qty) > num(line.stock);
            item.innerHTML = `
                <div class="pos-line__info">
                    <strong class="pos-line__name"></strong>
                    <small class="text-muted pos-line__meta"></small>
                </div>
                <div class="pos-line__qty">
                    <button type="button" class="btn btn-outline-secondary" data-act="dec" aria-label="-">−</button>
                    <input type="number" min="0.01" step="any" inputmode="decimal" class="form-control text-center" data-act="qty">
                    <button type="button" class="btn btn-outline-secondary" data-act="inc" aria-label="+">+</button>
                </div>
                <button type="button" class="btn btn-link pos-line__price" data-act="price"></button>
                <strong class="pos-line__total"></strong>
                <button type="button" class="btn btn-link text-danger pos-line__remove" data-act="remove"><i class="bi bi-x-lg"></i></button>`;
            item.querySelector(".pos-line__name").textContent = line.name;
            item.querySelector(".pos-line__meta").textContent = [line.sku, stockWarn ? (S.low_stock || "Not enough stock") : ""]
                .filter(Boolean).join(" · ");
            if (stockWarn) item.classList.add("pos-line--warn");
            item.querySelector("[data-act=qty]").value = line.qty;
            const price = item.querySelector("[data-act=price]");
            price.textContent = money(line.unit != null ? line.unit : line.price);
            price.title = S.edit_price || "Change price";
            if (discounted) price.classList.add("pos-line__price--discounted");
            item.querySelector(".pos-line__total").textContent = money(lineTotal(line));
            item.querySelector("[data-act=remove]").setAttribute("aria-label", S.remove || "Remove");
            item.dataset.index = String(index);
            linesBox.appendChild(item);
        });
        const t = totals();
        $("[data-pos-count]").textContent = String(cart.lines.reduce((sum, line) => sum + num(line.qty), 0));
        $("[data-pos-empty]").hidden = cart.lines.length > 0;
        $("[data-pos-subtotal]").textContent = money(t.subtotal);
        $("[data-pos-discount-value]").textContent = t.discount ? "−" + money(t.discount) : "0.00";
        $("[data-pos-total]").textContent = money(t.total);
        document.querySelectorAll("[data-pos-pay]").forEach((button) => { button.disabled = !cart.lines.length; });
        $("[data-pos-customer-name]").value = cart.customer.name || "";
        $("[data-pos-customer-phone]").value = cart.customer.phone || "";
        save();
    }

    function addItem(item) {
        if (item.variants && item.variants.length && !item.variant) {
            showResults([item], true);
            return;
        }
        const existing = cart.lines.find((line) => line.product === item.product && line.variant === (item.variant || null));
        if (existing) {
            existing.qty = num(existing.qty) + 1;
        } else {
            cart.lines.push({
                product: item.product, variant: item.variant || null, name: item.name, sku: item.sku,
                price: item.price, unit: null, qty: 1, stock: item.stock, track: item.track_stock,
            });
        }
        beep();
        flash((S.added || "Added") + ": " + item.name, "ok");
        unknown.hidden = true;
        render();
    }

    linesBox.addEventListener("click", (event) => {
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const index = Number(button.closest("[data-index]").dataset.index);
        const line = cart.lines[index];
        const act = button.dataset.act;
        if (act === "inc") line.qty = num(line.qty) + 1;
        if (act === "dec") line.qty = Math.max(num(line.qty) - 1, 0);
        if (act === "remove" || num(line.qty) <= 0) cart.lines.splice(index, 1);
        if (act === "price") {
            const value = window.prompt(S.price_prompt || "Unit price (LYD)", money(line.unit != null ? line.unit : line.price));
            if (value !== null && value.trim() !== "") line.unit = Math.max(num(value), 0);
            else if (value !== null) line.unit = null;
        }
        if (act !== "qty") render();
    });
    linesBox.addEventListener("change", (event) => {
        const input = event.target.closest("[data-act=qty]");
        if (!input) return;
        const index = Number(input.closest("[data-index]").dataset.index);
        const qty = num(input.value);
        if (qty > 0) cart.lines[index].qty = qty; else cart.lines.splice(index, 1);
        render();
    });

    $("[data-pos-clear]").addEventListener("click", () => {
        if (cart.lines.length && !window.confirm(S.clear_confirm || "Clear this sale?")) return;
        cart = blankCart();
        render();
        search.focus();
    });

    $("[data-pos-discount]").addEventListener("click", () => {
        const current = cart.discount.type === "percent" ? cart.discount.value + "%" : money(cart.discount.value);
        const hint = setup.unlimitedDiscount ? "" : " (" + (S.limit || "limit") + " " + setup.maxDiscount + "%)";
        const value = window.prompt((S.discount_prompt || "Discount — amount, or a percent like 5%") + hint, current);
        if (value === null) return;
        const text = value.trim();
        cart.discount = text.endsWith("%")
            ? {type: "percent", value: Math.max(num(text.slice(0, -1)), 0)}
            : {type: "amount", value: Math.max(num(text), 0)};
        render();
    });

    ["name", "phone"].forEach((field) => {
        $(`[data-pos-customer-${field}]`).addEventListener("input", (event) => {
            cart.customer[field] = event.target.value;
            save();
        });
    });

    // ---- lookup -------------------------------------------------------
    function showResults(items, choosingVariant) {
        results.replaceChildren();
        items.forEach((item) => {
            const entries = choosingVariant && item.variants.length
                ? item.variants.map((variant) => Object.assign({}, item, {
                    variant: variant.id, name: item.name + " — " + variant.label, stock: variant.stock, variants: [],
                }))
                : [item];
            entries.forEach((entry) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "pos-result";
                button.setAttribute("role", "listitem");
                const stockText = !entry.track_stock ? "" :
                    (entry.stock > 0 ? (S.in_stock || "In stock") + ": " + entry.stock : (S.out_of_stock || "Out of stock"));
                button.innerHTML = '<span class="pos-result__name"></span><span class="pos-result__meta"></span><strong class="pos-result__price"></strong>';
                button.querySelector(".pos-result__name").textContent = entry.name;
                button.querySelector(".pos-result__meta").textContent = [entry.sku, entry.category, stockText].filter(Boolean).join(" · ");
                button.querySelector(".pos-result__price").textContent = money(entry.price) + " LYD";
                if (entry.track_stock && entry.stock <= 0) button.classList.add("pos-result--out");
                button.addEventListener("click", () => { addItem(entry); search.focus(); });
                results.appendChild(button);
            });
        });
    }

    function showUnknown(code) {
        results.replaceChildren();
        unknown.hidden = false;
        $("[data-pos-unknown-text]").textContent = (S.not_found || "Nothing matches") + ": " + code;
        const add = $("[data-pos-unknown-add]");
        add.hidden = !setup.addProduct || !/^[0-9A-Za-z\-]{4,}$/.test(code);
        add.dataset.code = code;
    }

    function runLookup(text, fromScan) {
        const query = text.trim();
        if (!query) { results.replaceChildren(); unknown.hidden = true; return Promise.resolve(); }
        return getJSON(setup.lookup + "?q=" + encodeURIComponent(query)).then((data) => {
            if (data.exact && data.items.length === 1) {
                addItem(data.items[0]);
                search.value = "";
                results.replaceChildren();
                return;
            }
            if (!data.items.length) {
                if (fromScan) showUnknown(query);
                else { results.replaceChildren(); unknown.hidden = true; }
                return;
            }
            unknown.hidden = true;
            showResults(data.items, false);
        }).catch(() => flash(S.network || "Connection problem — try again.", "error"));
    }

    let typing = null;
    search.addEventListener("input", () => {
        clearTimeout(typing);
        typing = setTimeout(() => runLookup(search.value, false), 250);
    });
    search.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        clearTimeout(typing);
        runLookup(search.value, true);
    });

    // A hardware scanner types into whatever has focus; route stray keys here.
    document.addEventListener("keydown", (event) => {
        if (!payDialog.hidden || !doneDialog.hidden || event.ctrlKey || event.metaKey || event.altKey) return;
        const target = event.target;
        if (target && (target.closest("input, textarea, select, [contenteditable]") || target.closest(".modal"))) return;
        if (event.key.length === 1) {
            event.preventDefault();
            search.focus();
            search.value += event.key;
        } else if (event.key === "Enter" && search.value) {
            event.preventDefault();
            runLookup(search.value, true);
        }
    });

    $("[data-pos-unknown-add]").addEventListener("click", (event) => {
        const code = event.currentTarget.dataset.code;
        try { localStorage.setItem(pendingKey, code); } catch (error) { /* ignore */ }
        const opener = document.createElement("button");
        opener.type = "button";
        opener.hidden = true;
        opener.setAttribute("data-dynamic-modal", setup.addProduct + "?barcode=" + encodeURIComponent(code));
        opener.setAttribute("data-modal-title", S.add_unknown_title || "New item");
        document.body.appendChild(opener);
        opener.click();
        opener.remove();
    });

    // ---- payment ------------------------------------------------------
    const amountInputs = () => Array.from(document.querySelectorAll("[data-pos-amount]"));

    function payState() {
        const total = totals().total;
        let nonCash = 0;
        let cash = 0;
        amountInputs().forEach((input) => {
            const value = num(input.value);
            if (input.dataset.posAmount === "cash") cash += value; else nonCash += value;
        });
        const cashDue = Math.max(total - nonCash, 0);
        return {total, nonCash, cash, change: Math.max(cash - cashDue, 0), covered: nonCash <= total + 0.001 && nonCash + cash + 0.001 >= total};
    }

    function refreshPay() {
        const state = payState();
        $("[data-pos-change]").textContent = money(state.change);
        $("[data-pos-complete]").disabled = !state.covered;
        const error = $("[data-pos-pay-error]");
        error.hidden = state.nonCash <= state.total + 0.001;
        error.textContent = S.card_over || "Card or transfer is more than the total.";
    }

    function openPay(method) {
        const t = totals();
        $("[data-pos-pay-total]").textContent = money(t.total);
        amountInputs().forEach((input) => { input.value = input.dataset.posAmount === method ? money(t.total) : ""; });
        const quick = $("[data-pos-quick-cash]");
        quick.replaceChildren();
        if (setup.methods.includes("cash")) {
            const options = [t.total, Math.ceil(t.total / 5) * 5, Math.ceil(t.total / 10) * 10, Math.ceil(t.total / 50) * 50, Math.ceil(t.total / 100) * 100];
            [...new Set(options.map((value) => money(value)))].forEach((value) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-outline-secondary rounded-pill";
                button.textContent = value;
                button.addEventListener("click", () => {
                    const cash = $('[data-pos-amount="cash"]');
                    if (cash) { cash.value = value; refreshPay(); }
                });
                quick.appendChild(button);
            });
        }
        $("[data-pos-pay-error]").hidden = true;
        payDialog.hidden = false;
        refreshPay();
        const first = $(`[data-pos-amount="${method}"]`);
        if (first) { first.focus(); first.select(); }
    }

    document.querySelectorAll("[data-pos-pay]").forEach((button) => {
        button.addEventListener("click", () => { if (cart.lines.length) openPay(button.dataset.posPay); });
    });
    payDialog.addEventListener("input", refreshPay);
    $("[data-pos-pay-cancel]").addEventListener("click", () => { payDialog.hidden = true; search.focus(); });

    let lastSale = null;
    $("[data-pos-complete]").addEventListener("click", (event) => {
        const button = event.currentTarget;
        const t = totals();
        const payments = amountInputs()
            .filter((input) => num(input.value) > 0)
            .map((input) => ({method: input.dataset.posAmount, amount: money(input.value)}));
        const body = {
            key: cart.key,
            till: setup.till,
            lines: cart.lines.map((line) => ({
                product: line.product, variant: line.variant, qty: line.qty,
                price: line.unit != null ? money(line.unit) : null,
            })),
            discount: money(t.discount),
            customer_name: cart.customer.name,
            customer_phone: cart.customer.phone,
            payments,
        };
        button.disabled = true;
        fetch(setup.checkout, {
            method: "POST",
            headers: {"Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest"},
            body: JSON.stringify(body),
        }).then((response) => response.json().then((data) => ({ok: response.ok, data})))
            .then(({ok, data}) => {
                if (!ok || !data.ok) {
                    const error = $("[data-pos-pay-error]");
                    error.textContent = data.error || (S.failed || "The sale could not be completed.");
                    error.hidden = false;
                    button.disabled = false;
                    return;
                }
                lastSale = data;
                payDialog.hidden = true;
                cart = blankCart();
                render();
                $("[data-pos-done-number]").textContent = data.number;
                $("[data-pos-done-change]").textContent = money(data.change);
                $("[data-pos-done-change-row]").hidden = num(data.change) <= 0;
                $("[data-pos-print]").hidden = setup.receiptSize === "none";
                doneDialog.hidden = false;
                $("[data-pos-new]").focus();
            })
            .catch(() => {
                // The key is kept, so pressing again cannot sell twice.
                const error = $("[data-pos-pay-error]");
                error.textContent = S.network || "Connection problem — try again.";
                error.hidden = false;
                button.disabled = false;
            });
    });

    $("[data-pos-print]").addEventListener("click", () => {
        if (!lastSale) return;
        const frame = $("[data-pos-print-frame]");
        frame.onload = () => { try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (error) { window.open(frame.src); } };
        frame.src = lastSale.receipt;
    });
    $("[data-pos-new]").addEventListener("click", () => { doneDialog.hidden = true; search.focus(); });

    // ---- camera -------------------------------------------------------
    const cameraButton = $("[data-pos-camera]");
    const cameraView = $("[data-pos-camera-view]");
    const video = $("[data-pos-video]");
    let stream = null;
    let scanning = false;
    let lastCode = "";
    let lastAt = 0;

    if ("BarcodeDetector" in window && window.isSecureContext && navigator.mediaDevices) {
        cameraButton.hidden = false;
    }

    function stopCamera() {
        scanning = false;
        if (stream) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        cameraView.hidden = true;
        search.focus();
    }

    cameraButton.addEventListener("click", () => {
        const detector = new window.BarcodeDetector({
            formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "code_93", "itf", "codabar", "qr_code"],
        });
        navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}}).then((media) => {
            stream = media;
            video.srcObject = media;
            video.play();
            cameraView.hidden = false;
            scanning = true;
            $("[data-pos-camera-status]").textContent = S.camera_hint || "Point the camera at a barcode.";
            const tick = () => {
                if (!scanning) return;
                detector.detect(video).then((codes) => {
                    const code = codes.length ? codes[0].rawValue : "";
                    const now = Date.now();
                    if (code && (code !== lastCode || now - lastAt > 1500)) {
                        lastCode = code;
                        lastAt = now;
                        runLookup(code, true);
                    }
                }).catch(() => {}).finally(() => setTimeout(tick, 200));
            };
            tick();
        }).catch(() => flash(S.camera_denied || "The camera could not be opened.", "error"));
    });
    $("[data-pos-camera-close]").addEventListener("click", stopCamera);

    // ---- find by vehicle ---------------------------------------------
    const vehicleToggle = $("[data-pos-vehicle-toggle]");
    const vehiclePanel = $("[data-pos-vehicle]");
    if (setup.vehicle && setup.vehicleSearch) {
        vehicleToggle.hidden = false;
        const vehicleSearch = $("[data-pos-vehicle-search]");
        const vehicleResults = $("[data-pos-vehicle-results]");
        vehicleToggle.addEventListener("click", () => {
            vehiclePanel.hidden = !vehiclePanel.hidden;
            if (!vehiclePanel.hidden) vehicleSearch.focus();
        });
        let vehicleTimer = null;
        vehicleSearch.addEventListener("input", () => {
            clearTimeout(vehicleTimer);
            vehicleTimer = setTimeout(() => {
                const query = vehicleSearch.value.trim();
                if (query.length < 2) { vehicleResults.replaceChildren(); return; }
                getJSON(setup.vehicleSearch + "?jump=1&q=" + encodeURIComponent(query)).then((data) => {
                    vehicleResults.replaceChildren();
                    (data.results || []).forEach((chip) => {
                        const button = document.createElement("button");
                        button.type = "button";
                        button.className = "list-group-item list-group-item-action";
                        button.textContent = chip.label;
                        button.addEventListener("click", () => pickVehicle(chip));
                        vehicleResults.appendChild(button);
                    });
                });
            }, 200);
        });
        const pickVehicle = (chip) => {
            const params = new URLSearchParams({make: chip.make, model: chip.vehicle_model});
            if (chip.generation) params.set("generation", chip.generation);
            if (chip.engine) params.set("engine", chip.engine);
            if (chip.year_from && chip.year_from === chip.year_to) params.set("year", chip.year_from);
            else params.set("any_year", "1");
            getJSON(setup.vehicle + "?" + params.toString()).then((data) => {
                vehicleResults.replaceChildren();
                $("[data-pos-vehicle-path]").textContent = chip.label + " · " + data.items.length + " " + (S.items || "items");
                showResults(data.items.map((item) => Object.assign({variants: []}, item)), false);
            });
        };
    }

    // ---- start --------------------------------------------------------
    render();
    try {
        const pending = localStorage.getItem(pendingKey);
        if (pending) {
            localStorage.removeItem(pendingKey);
            runLookup(pending, true);
        }
    } catch (error) { /* ignore */ }
    search.focus();
})();
