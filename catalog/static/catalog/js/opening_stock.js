(function () {
    const products = JSON.parse(document.getElementById('product-map').textContent || '{}');
    const options = Array.from(document.querySelectorAll('#product-datalist option'));
    const form = document.getElementById("opening-stock-editor");
    const config = JSON.parse(document.getElementById("opening-stock-config").textContent);
    const prefix = form.dataset.prefix;
    const totalForms = document.getElementById('id_' + prefix + '-TOTAL_FORMS');
    const body = document.getElementById('items-body');

    function q(row, suffix) { return row.querySelector('[name$="-' + suffix + '"]'); }

    // Match a typed/selected name against the datalist to find the product id.
    function matchId(value) {
        const v = (value || '').trim().toLowerCase();
        const matches = options.filter((o) => o.value.trim().toLowerCase() === v);
        const opt = matches.length === 1 ? matches[0] : null;
        return opt ? (opt.dataset.id || '') : '';
    }

    // Fill a field unless the user already edited it by hand. Opening-stock rows
    // start with defaults like 0.00 and "piece"; those still count as untouched
    // and must be replaced when an existing product is selected.
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

    function syncRow(row) {
        const nameInput = q(row, 'name');
        const hiddenFk = q(row, 'product');
        const id = matchId(nameInput ? nameInput.value : '');
        if (hiddenFk) hiddenFk.value = id;  // blank id → a new product is created on apply
        if (id && products[id]) {
            const d = products[id];
            setAuto(q(row, 'alias'), d.alias);
            setAuto(q(row, 'currency'), d.currency);
            q(row, 'currency').dispatchEvent(new Event('change', {bubbles: true}));
            setAuto(q(row, 'cost_usd'), d.cost);
            setAuto(q(row, 'markup_percent'), d.markup);
            setAuto(q(row, 'price_usd'), d.price_usd);
            setAuto(q(row, 'price_lyd_override'), d.price_lyd);
            setAuto(q(row, 'barcode'), d.barcode);
            setAuto(q(row, 'color'), d.color);
            setAuto(q(row, 'size'), d.size);
            setAuto(q(row, 'category'), d.category);
            setAuto(q(row, 'unit'), d.unit);
        }
    }

    function wireRow(row) {
        const nameInput = q(row, 'name');
        if (nameInput) {
            nameInput.addEventListener('input', () => syncRow(row));
            nameInput.addEventListener('change', () => syncRow(row));
        }
        // Clear the autofilled flag once the user edits a field by hand.
        [
            'alias', 'currency', 'cost_usd', 'markup_percent', 'price_usd', 'price_lyd_override', 'barcode',
            'color', 'size', 'category', 'unit'
        ].forEach((f) => {
            const el = q(row, f);
            if (el) el.addEventListener('input', () => markManual(el));
            if (el) el.addEventListener('change', () => markManual(el));
        });
        const del = row.querySelector('.del-line');
        if (del) del.addEventListener('click', () => {
            const compatibility = row.nextElementSibling;
            if (compatibility?.classList.contains('line-compatibility-row')) {
                compatibility.hidden = true;
                compatibility.querySelectorAll('input,select').forEach((input) => { input.disabled = true; });
            }
            const delInput = q(row, 'DELETE');
            if (delInput) {
                delInput.checked = true;
                row.hidden = true;
                row.querySelectorAll("input,select").forEach((input) => { if (input !== delInput) input.disabled = true; });
            }
            else { row.remove(); }
        });
    }

    function appendRow(values = {}) {
        const idx = Number(totalForms.value);
        const holder = document.createElement('tbody');
        holder.innerHTML = document.getElementById('empty-form-row').innerHTML.replace(/__prefix__/g, idx).trim();
        const row = holder.querySelector('.line-row');
        Object.entries(values).forEach(([name, value]) => {
            const input = q(row, name);
            if (input) {
                input.value = value == null ? '' : value;
                input.dataset.userEdited = '1';
            }
        });
        body.append(...holder.children);
        totalForms.value = idx + 1;
        wireRow(row);
        if (window.initCatalogColorPalettes) window.initCatalogColorPalettes();
        return row;
    }

    document.getElementById('add-line').addEventListener('click', () => appendRow());
    body.querySelectorAll('.line-row').forEach((row) => {
        wireRow(row);
        if (row.dataset.preserveValues === 'true') {
            row.querySelectorAll('input,select').forEach((input) => { input.dataset.userEdited = '1'; });
        }
    });
    form.addEventListener('submit', (event) => {
        if (event.submitter?.value !== 'save_draft' && !window.confirm(config.confirm)) event.preventDefault();
    });

    const file = document.getElementById('opening-stock-file');
    const check = document.getElementById('opening-stock-import-check');
    const insert = document.getElementById('opening-stock-import-insert');
    const status = document.getElementById('opening-stock-import-status');
    const preview = document.getElementById('opening-stock-import-preview');
    let editorRows = [];
    let checking = false;

    function message(text, tone = 'info') {
        status.replaceChildren();
        const alert = document.createElement('div');
        alert.className = 'alert alert-' + tone + ' mb-0';
        alert.textContent = text;
        status.appendChild(alert);
    }
    file.addEventListener('change', () => {
        editorRows = [];
        insert.disabled = true;
        check.disabled = !file.files.length;
        preview.classList.add('d-none');
        status.replaceChildren();
    });
    check.addEventListener('click', async () => {
        if (!file.files.length || checking) return;
        checking = true;
        check.disabled = true;
        file.disabled = true;
        insert.disabled = true;
        editorRows = [];
        preview.classList.add('d-none');
        message(config.verifying);
        const payload = new FormData();
        payload.append('csrfmiddlewaretoken', form.querySelector('[name="csrfmiddlewaretoken"]').value);
        payload.append('file', file.files[0]);
        try {
            const response = await fetch(form.dataset.previewUrl, {method: 'POST', body: payload});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || config.failed);
            const rows = document.getElementById('opening-stock-import-rows');
            rows.replaceChildren();
            data.rows.forEach((entry) => {
                const row = document.createElement('tr');
                if (entry.errors.length) row.className = 'table-danger';
                [entry.row, entry.name, entry.variant, entry.quantity,
                 entry.action === 'create' ? config.newItem : config.existingItem,
                 entry.errors.length ? entry.errors.join('; ') : entry.changes.join(', ') || '—'].forEach((value) => {
                    const cell = document.createElement('td');
                    cell.textContent = value;
                    row.appendChild(cell);
                });
                rows.appendChild(row);
            });
            document.getElementById('opening-stock-import-summary').textContent = data.summary.total + ' ' + config.rows + ' · ' + data.summary.conflicts + ' ' + config.conflicts;
            preview.classList.remove('d-none');
            editorRows = data.editor_rows || [];
            insert.disabled = !data.can_insert;
            message(data.can_insert ? config.ready : config.fix, data.can_insert ? 'success' : 'warning');
        } catch (error) {
            message(error.message, 'danger');
        } finally {
            checking = false;
            file.disabled = false;
            check.disabled = !file.files.length;
        }
    });
    insert.addEventListener('click', () => {
        if (!editorRows.length) return;
        const activeRows = Array.from(body.querySelectorAll('.line-row')).filter((row) => !q(row, 'DELETE')?.checked);
        if (activeRows.filter((row) => q(row, 'name')?.value).length + editorRows.length > 1000) {
            message(config.limit, 'danger');
            return;
        }
        editorRows.forEach(appendRow);
        editorRows = [];
        insert.disabled = true;
        file.value = '';
        check.disabled = true;
        preview.classList.add('d-none');
        message(config.inserted, 'success');
        window.bootstrap.Modal.getInstance(document.getElementById('opening-stock-import-modal'))?.hide();
        form.dispatchEvent(new Event('change', {bubbles: true}));
    });
})();
