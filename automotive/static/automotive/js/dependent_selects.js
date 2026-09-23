(function () {
    "use strict";

    let dependencyData = null;
    let dependencyPromise = null;

    function endpoint() {
        const editor = document.querySelector("[data-fitment-editor]");
        return editor ? editor.dataset.dependenciesUrl : "/staff/automotive/dependencies/";
    }

    function loadDependencies() {
        if (dependencyData) return Promise.resolve(dependencyData);
        if (!dependencyPromise) {
            dependencyPromise = fetch(endpoint(), {headers: {"X-Requested-With": "XMLHttpRequest"}})
                .then(function (response) {
                    if (!response.ok) throw new Error("Could not load vehicle choices");
                    return response.json();
                })
                .then(function (data) { dependencyData = data; return data; });
        }
        return dependencyPromise;
    }

    function refill(select, items, keep) {
        if (!select) return;
        const blank = select.options.length ? select.options[0].textContent : "---------";
        select.replaceChildren(new Option(blank, ""));
        items.forEach(function (item) { select.add(new Option(item.label, String(item.id))); });
        if (keep && items.some(function (item) { return String(item.id) === String(keep); })) {
            select.value = String(keep);
        }
    }

    function bindFitmentRow(row, data) {
        if (!row || row.dataset.dependenciesBound === "1") return;
        row.dataset.dependenciesBound = "1";
        const model = row.querySelector("[data-fitment-vehicle-model]");
        const generation = row.querySelector("[data-fitment-generation]");
        const engine = row.querySelector("[data-fitment-engine]");
        const trim = row.querySelector("[data-fitment-trim]");

        function update(reset) {
            const modelId = model ? model.value : "";
            const generationId = generation ? generation.value : "";
            if (generation) {
                const keep = reset ? "" : generation.value;
                refill(generation, data.generations.filter(function (item) {
                    return String(item.model_id) === modelId;
                }), keep);
            }
            const activeGeneration = generation ? generation.value : generationId;
            [
                [engine, data.engines],
                [trim, data.trims],
            ].forEach(function (pair) {
                const select = pair[0];
                if (!select) return;
                const keep = reset ? "" : select.value;
                refill(select, pair[1].filter(function (item) {
                    if (String(item.model_id) !== modelId) return false;
                    if (!activeGeneration) return !item.generation_id;
                    return !item.generation_id || String(item.generation_id) === activeGeneration;
                }), keep);
            });
        }
        if (model) model.addEventListener("change", function () { update(true); });
        if (generation) generation.addEventListener("change", function () { update(false); });
        update(false);
    }

    function initializeEditor(editor, data) {
        const rows = editor.querySelector("[data-fitment-rows]");
        const total = editor.querySelector("[name='fitments-TOTAL_FORMS']");
        editor.querySelectorAll("[data-fitment-row]").forEach(function (row) { bindFitmentRow(row, data); });

        editor.addEventListener("click", function (event) {
            const add = event.target.closest("[data-add-fitment]");
            if (add) {
                const template = editor.querySelector("template[data-empty-fitment]");
                const index = Number(total.value);
                const holder = document.createElement("div");
                holder.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index)).trim();
                const row = holder.firstElementChild;
                rows.appendChild(row);
                total.value = String(index + 1);
                bindFitmentRow(row, data);
                return;
            }
            const remove = event.target.closest("[data-remove-fitment]");
            if (!remove) return;
            const row = remove.closest("[data-fitment-row]");
            const id = row.querySelector("input[name$='-id']");
            const deletion = row.querySelector("input[name$='-DELETE']");
            if (id && id.value && deletion) {
                deletion.checked = true;
                row.hidden = true;
            } else {
                row.remove();
            }
        });
    }

    function initializeModal(root, data) {
        root.querySelectorAll("select[data-automotive-parent='vehicle-model']").forEach(function (model) {
            if (model.dataset.dependenciesBound === "1") return;
            model.dataset.dependenciesBound = "1";
            const container = model.closest("form") || root;
            const generation = container.querySelector("select[data-automotive-child='generation']");
            function update(reset) {
                if (!generation) return;
                refill(generation, data.generations.filter(function (item) {
                    return String(item.model_id) === model.value;
                }), reset ? "" : generation.value);
            }
            model.addEventListener("change", function () { update(true); });
            update(false);
        });
    }

    function initialize(root) {
        const editor = root.querySelector ? root.querySelector("[data-fitment-editor]") : null;
        const hasModalFields = root.querySelector && root.querySelector("[data-automotive-parent]");
        if (!editor && !hasModalFields) return;
        loadDependencies().then(function (data) {
            if (editor && editor.dataset.editorBound !== "1") {
                editor.dataset.editorBound = "1";
                initializeEditor(editor, data);
            }
            initializeModal(root, data);
        }).catch(function () {});
    }

    document.addEventListener("DOMContentLoaded", function () { initialize(document); });
    new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
                if (node.nodeType === 1) initialize(node);
            });
        });
    }).observe(document.documentElement, {childList: true, subtree: true});
})();
