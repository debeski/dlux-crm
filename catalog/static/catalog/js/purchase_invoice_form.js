(function () {
    const products = JSON.parse(document.getElementById('product-map').textContent || '{}');
    const options = Array.from(document.querySelectorAll('#product-datalist option'));
    const form = document.getElementById('purchase-invoice-editor');
    if (!form) return;
    const prefix = form.dataset.prefix;
    const totalForms = document.getElementById('id_' + prefix + '-TOTAL_FORMS');
    const body = document.getElementById('items-body');
    const rates = JSON.parse(document.getElementById('currency-rates').textContent);
    const currencySelect = document.getElementById('id_currency');
    const mapCurrency = form.dataset.purchaseCurrency;
    let selectedCurrency = currencySelect.value || mapCurrency;
    let rate = Number(rates[selectedCurrency]);
    const fmt = (n) => (isNaN(n) ? 0 : n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

    function q(row, suffix) { return row.querySelector('[name$="-' + suffix + '"]'); }
    function matchId(value) {
        const v = (value || '').trim().toLowerCase();
        const matches = options.filter((o) => o.value.trim().toLowerCase() === v);
        const opt = matches.length === 1 ? matches[0] : null;
        return opt ? (opt.dataset.id || '') : '';
    }
    function setAuto(el, val) {
        if (!el) return;
        if (el.dataset.userEdited === '1') return;
        el.value = (val === '' || val === undefined || val === null) ? '' : val;
        el.dataset.autofilled = '1';
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    function markManual(el) {
        if (document.activeElement !== el) return;
        el.dataset.autofilled = '';
        el.dataset.userEdited = '1';
    }
    function recalcRow(row) {
        if (row.style.display === 'none') return 0;
        const cost = parseFloat(q(row, 'cost_usd')?.value) || 0;
        const qty = parseFloat(q(row, 'quantity')?.value) || 0;
        const totalUsd = cost * qty;
        const totalLyd = totalUsd * rate;
        const usdCell = row.querySelector('.line-total-usd');
        const lydCell = row.querySelector('.line-total-lyd');
        if (usdCell) usdCell.textContent = fmt(totalUsd);
        if (lydCell) lydCell.textContent = fmt(totalLyd);
        return totalUsd;
    }
    function recalcAll() {
        let totalUsd = 0;
        body.querySelectorAll('.line-row').forEach((row) => { totalUsd += recalcRow(row); });
        document.getElementById('total-usd-cell').textContent = fmt(totalUsd);
        document.getElementById('total-lyd-cell').textContent = fmt(totalUsd * rate);
    }
    function syncRow(row) {
        const nameInput = q(row, 'name');
        const hiddenFk = q(row, 'product');
        const id = matchId(nameInput ? nameInput.value : '');
        if (hiddenFk) hiddenFk.value = id;
        if (id && products[id]) {
            const d = products[id];
            setAuto(q(row, 'alias'), d.alias);
            setAuto(q(row, 'currency'), d.currency);
            q(row, 'currency').dispatchEvent(new Event('change', {bubbles: true}));
            setAuto(q(row, 'cost_usd'), (d.cost * Number(rates[mapCurrency]) / rate).toFixed(2));
            setAuto(q(row, 'markup_percent'), d.markup);
            setAuto(q(row, 'price_usd'), (d.price_usd * Number(rates[mapCurrency]) / rate).toFixed(2));
            setAuto(q(row, 'price_lyd_override'), d.price_lyd);
            setAuto(q(row, 'barcode'), d.barcode);
            setAuto(q(row, 'color'), d.color);
            setAuto(q(row, 'size'), d.size);
            setAuto(q(row, 'category'), d.category);
            setAuto(q(row, 'unit'), d.unit);
        }
        recalcAll();
    }
    currencySelect.addEventListener('change', () => {
        const previousRate = rate;
        selectedCurrency = currencySelect.value;
        rate = Number(rates[selectedCurrency]);
        document.querySelectorAll('[data-purchase-currency]').forEach(el => { el.textContent = selectedCurrency; });
        document.getElementById('purchase-rate').textContent = rate;
        body.querySelectorAll('.line-row').forEach(row => {
            ['cost_usd', 'price_usd'].forEach(name => {
                const input = q(row, name);
                if (input && input.value !== '') input.value = (Number(input.value) * previousRate / rate).toFixed(2);
            });
            q(row, 'price_lyd_override').setAttribute('data-usd-rate', rate);
            if (!q(row, 'product').value && q(row, 'currency').dataset.autofilled !== '') q(row, 'currency').value = selectedCurrency;
        });
        recalcAll();
    });
    function wireRow(row) {
        q(row, 'price_lyd_override').setAttribute('data-usd-rate', rate);
        const nameInput = q(row, 'name');
        if (nameInput) {
            nameInput.addEventListener('input', () => syncRow(row));
            nameInput.addEventListener('change', () => syncRow(row));
        }
        [
            'alias', 'currency', 'cost_usd', 'markup_percent', 'price_usd', 'price_lyd_override', 'barcode',
            'color', 'size', 'category', 'unit'
        ].forEach((f) => {
            const el = q(row, f);
            if (el) el.addEventListener('input', () => { markManual(el); recalcAll(); });
            if (el) el.addEventListener('change', () => { markManual(el); recalcAll(); });
        });
        const qty = q(row, 'quantity');
        if (qty) qty.addEventListener('input', recalcAll);
        const del = row.querySelector('.del-line');
        if (del) del.addEventListener('click', () => {
            const compatibility = row.nextElementSibling;
            if (compatibility?.classList.contains('line-compatibility-row')) {
                compatibility.hidden = true;
                compatibility.querySelectorAll('input,select').forEach((input) => { input.disabled = true; });
            }
            const delInput = q(row, 'DELETE');
            if (delInput) { delInput.checked = true; row.style.display = 'none'; }
            else { row.remove(); }
            recalcAll();
        });
    }

    document.getElementById('add-line').addEventListener('click', () => {
        const idx = parseInt(totalForms.value, 10);
        const html = document.getElementById('empty-form-row').innerHTML.replace(/__prefix__/g, idx);
        const holder = document.createElement('tbody');
        holder.innerHTML = html.trim();
        const tr = holder.querySelector('.line-row');
        body.append(...holder.children);
        totalForms.value = idx + 1;
        q(tr, 'currency').value = selectedCurrency;
        wireRow(tr);
        if (window.initCatalogColorPalettes) window.initCatalogColorPalettes();
        if (window.AutomotiveFitsPicker) window.AutomotiveFitsPicker.initAll(body);
    });

    body.querySelectorAll('.line-row').forEach(wireRow);
    recalcAll();
})();

(function () {
    const nameInput = document.querySelector('[data-supplier-input]');
    if (!nameInput) return;
    const hiddenFk = document.getElementById('id_supplier');
    const phone = document.getElementById('id_supplier_phone');
    const address = document.getElementById('id_supplier_address');
    const options = Array.from(document.querySelectorAll('#supplier-datalist option'));

    function matchOption(value) {
        const v = (value || '').trim().toLowerCase();
        return options.find((o) => o.value.trim().toLowerCase() === v) || null;
    }
    function setAuto(el, val) {
        if (!el) return;
        if (el.value && el.dataset.autofilled !== '1') return;
        el.value = val || '';
        el.dataset.autofilled = '1';
    }
    function sync() {
        const opt = matchOption(nameInput.value);
        if (opt) {
            if (hiddenFk) hiddenFk.value = opt.dataset.id || '';
            setAuto(phone, opt.dataset.phone);
            setAuto(address, opt.dataset.address);
        } else if (hiddenFk) {
            hiddenFk.value = '';
        }
    }
    [phone, address].forEach((el) => {
        if (el) el.addEventListener('input', () => {
            if (document.activeElement === el) el.dataset.autofilled = '';
        });
    });
    nameInput.addEventListener('input', sync);
    nameInput.addEventListener('change', sync);
})();
