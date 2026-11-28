// Deposit combobox: match the typed reference against the datalist and
// set the hidden deposit FK (blank = a new batch is created on save).
(function () {
    const input = document.querySelector('[data-deposit-input]');
    if (!input || input.dataset.depositComboboxReady) return;
    input.dataset.depositComboboxReady = '1';
    const hidden = document.getElementById('id_deposit');
    const options = Array.from(document.querySelectorAll('#deposit-datalist option'));
    function sync() {
        const v = (input.value || '').trim().toLowerCase();
        const opt = options.find((o) => o.value.trim().toLowerCase() === v);
        if (hidden) hidden.value = opt ? (opt.dataset.id || '') : '';
    }
    input.addEventListener('input', sync);
    input.addEventListener('change', sync);
})();
