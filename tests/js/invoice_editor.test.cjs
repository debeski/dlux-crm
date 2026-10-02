const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync('sales/static/sales/js/invoice_editor.js', 'utf8');
const removeRow = source.slice(source.indexOf('        function removeRow(row)'), source.indexOf('        function wireRow(row)'));

for (const persisted of [false, true]) {
    test(`removing ${persisted ? 'saved' : 'new'} rows preserves DELETE and id for submission`, () => {
        const inputs = [
            {name: 'items-1-DELETE', checked: false},
            {name: 'items-1-id', value: persisted ? '12' : ''},
            {name: 'items-1-quantity', value: ''},
            {name: 'items-1-kind', value: 'custom'},
        ];
        const classes = new Set();
        const row = {
            classList: {add: value => classes.add(value)},
            querySelectorAll: () => inputs,
        };
        let recalculated = 0;
        const context = {
            row,
            field: (_, name) => inputs.find(input => input.name.endsWith('-' + name)),
            recalcAll: () => recalculated++,
        };
        vm.runInNewContext(removeRow + '\nremoveRow(row);', context);
        assert.equal(inputs[0].checked, true);
        assert.equal(inputs[0].disabled, undefined);
        assert.equal(inputs[1].disabled, undefined);
        assert.equal(inputs[2].disabled, true);
        assert.equal(inputs[3].disabled, true);
        assert.equal(classes.has('d-none'), true);
        assert.equal(recalculated, 1);
    });
}
