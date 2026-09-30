/*
 * Quick "Fits" picker: type a vehicle, pick a suggestion, repeat.
 *
 * Each [data-fits-picker] owns a hidden JSON input of chips. A chip with an
 * `id` is an existing compatibility row; one without is a new row described by
 * vehicle_model / generation / engine / years. The server re-validates every
 * chip, so this file only handles entry speed.
 *
 * Loaded by the widget markup itself. The modal re-runs injected scripts on
 * first load only, so pickers are also bound on `dlux:modal-content-loaded`;
 * rows added later (intake grids) call `window.AutomotiveFitsPicker.initAll`.
 */
(function () {
    "use strict";

    if (window.AutomotiveFitsPicker) {
        window.AutomotiveFitsPicker.initAll(document);
        return;
    }

    const KEY_FIELDS = ["vehicle_model", "generation", "engine", "trim", "transmission", "position", "year_from", "year_to"];

    function chipKey(chip) {
        if (chip.id != null) return "id:" + chip.id;
        return KEY_FIELDS.map(function (field) { return chip[field] == null ? "" : String(chip[field]); }).join("|");
    }

    function parse(value) {
        try {
            const data = JSON.parse(value || "[]");
            return Array.isArray(data) ? data : [];
        } catch (error) {
            return [];
        }
    }

    function debounce(fn, wait) {
        let timer = null;
        return function () {
            const args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(null, args); }, wait);
        };
    }

    function getJSON(url) {
        return fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}})
            .then(function (response) {
                if (!response.ok) throw new Error("HTTP " + response.status);
                return response.json();
            });
    }

    function withQuery(base, params) {
        const url = new URL(base, window.location.origin);
        Object.keys(params).forEach(function (key) { url.searchParams.set(key, params[key]); });
        return url.toString();
    }

    function bind(root) {
        if (!root || root.dataset.fitsBound === "1") return;
        root.dataset.fitsBound = "1";

        const jump = root.dataset.fitsMode === "jump";
        const hidden = root.querySelector("[data-fits-value]") || document.createElement("input");
        const chipsBox = root.querySelector("[data-fits-chips]");
        const search = root.querySelector("[data-fits-search]");
        const results = root.querySelector("[data-fits-results]");
        const copyToggle = root.querySelector("[data-fits-copy-toggle]");
        const copyBox = root.querySelector("[data-fits-copy]");
        const copySearch = root.querySelector("[data-fits-copy-search]");
        const copyResults = root.querySelector("[data-fits-copy-results]");
        const strings = root.dataset;

        let chips = parse(hidden.value);
        let suggestions = [];
        let active = -1;

        function sync() {
            hidden.value = JSON.stringify(chips);
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
            root.dispatchEvent(new CustomEvent("fits:change", {bubbles: true, detail: {count: chips.length}}));
        }

        function renderChips() {
            if (!chipsBox) return;
            const details = root.closest("details");
            const counter = details && details.querySelector("[data-fits-count]");
            if (counter) counter.textContent = String(chips.length);
            chipsBox.replaceChildren();
            if (!chips.length) {
                const empty = document.createElement("span");
                empty.className = "fits-picker__empty";
                empty.textContent = strings.strEmpty || "";
                chipsBox.appendChild(empty);
                return;
            }
            chips.forEach(function (chip, index) {
                const item = document.createElement("span");
                item.className = "fits-chip" + (chip.id == null ? " fits-chip--new" : "");
                const label = document.createElement("span");
                label.textContent = chip.label || "";
                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "fits-chip__remove";
                remove.setAttribute("aria-label", (strings.strRemove || "Remove") + " " + (chip.label || ""));
                remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
                remove.addEventListener("click", function () {
                    chips.splice(index, 1);
                    renderChips();
                    sync();
                });
                item.append(label, remove);
                chipsBox.appendChild(item);
            });
        }

        function vehicleName(chip) {
            return String(chip.label || "").split(" · ")[0];
        }

        function suggestName(chip) {
            const form = root.closest("form");
            if (!form || root.dataset.suggestName !== "1") return;
            const name = form.querySelector('[name="name"]');
            const category = form.querySelector('select[name="category"]');
            if (!name || name.value.trim() || !category || !category.value) return;
            const option = category.options[category.selectedIndex];
            name.value = option.textContent.trim() + " – " + vehicleName(chip);
            name.dispatchEvent(new Event("input", {bubbles: true}));
        }

        function addChips(list) {
            const known = new Set(chips.map(chipKey));
            let added = 0;
            list.forEach(function (chip) {
                const key = chipKey(chip);
                if (known.has(key)) return;
                known.add(key);
                chips.push(chip);
                added += 1;
            });
            if (added) {
                if (chips.length === added) suggestName(chips[0]);
                renderChips();
                sync();
            }
            return added;
        }

        function closeResults() {
            results.hidden = true;
            results.replaceChildren();
            suggestions = [];
            active = -1;
        }

        function highlight(index) {
            const items = results.querySelectorAll("[data-index]");
            items.forEach(function (node) { node.classList.toggle("active", Number(node.dataset.index) === index); });
            active = index;
            const current = results.querySelector('[data-index="' + index + '"]');
            if (current) current.scrollIntoView({block: "nearest"});
        }

        function jumpTo(chip) {
            const params = {make: chip.make, model: chip.vehicle_model};
            if (!chip.needs_year && !chip.all_years) {
                const typed = (search.value.match(/\b(?:19|20)\d{2}\b/) || [])[0];
                const year = typed ? Number(typed) : NaN;
                params.year = year >= chip.year_from && year <= chip.year_to ? year : chip.year_to;
                if (chip.generation) params.generation = chip.generation;
                if (chip.engine) params.engine = chip.engine;
            }
            window.location.assign(withQuery(root.dataset.browseUrl, params));
        }

        function choose(index) {
            const chip = suggestions[index];
            if (chip && jump) {
                jumpTo(chip);
                return;
            }
            if (!chip || chip.needs_year) return;
            const clean = Object.assign({}, chip);
            delete clean.needs_year;
            addChips([clean]);
            search.value = "";
            closeResults();
            search.focus();
        }

        function renderResults(list) {
            suggestions = list;
            results.replaceChildren();
            if (!list.length) {
                const none = document.createElement("div");
                none.className = "list-group-item text-muted small";
                none.textContent = strings.strNoResults || "";
                results.appendChild(none);
            }
            const known = new Set(chips.map(chipKey));
            list.forEach(function (chip, index) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "list-group-item list-group-item-action fits-picker__option";
                button.dataset.index = String(index);
                button.setAttribute("role", "option");
                button.textContent = chip.label;
                if (chip.needs_year && !jump) {
                    button.disabled = true;
                    button.classList.add("text-muted");
                } else if (known.has(chipKey(chip))) {
                    button.classList.add("fits-picker__option--added");
                    const badge = document.createElement("span");
                    badge.className = "badge text-bg-light border ms-2";
                    badge.textContent = strings.strAdded || "";
                    button.appendChild(badge);
                }
                button.addEventListener("mousedown", function (event) { event.preventDefault(); });
                button.addEventListener("click", function () { choose(index); });
                results.appendChild(button);
            });
            results.hidden = false;
            const first = list.findIndex(function (chip) { return jump || !chip.needs_year; });
            if (first >= 0) highlight(first);
        }

        const runSearch = debounce(function (query) {
            if (query.trim().length < 2) {
                closeResults();
                return;
            }
            const params = jump ? {q: query, jump: "1"} : {q: query};
            getJSON(withQuery(root.dataset.searchUrl, params))
                .then(function (data) {
                    if (search.value === query) renderResults(data.results || []);
                })
                .catch(closeResults);
        }, 180);

        search.addEventListener("input", function () { runSearch(search.value); });
        search.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                if (!results.hidden && active >= 0) choose(active);
                return;
            }
            if (results.hidden) return;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const step = event.key === "ArrowDown" ? 1 : -1;
                let next = active;
                for (let i = 0; i < suggestions.length; i += 1) {
                    next = (next + step + suggestions.length) % suggestions.length;
                    if (jump || !suggestions[next].needs_year) break;
                }
                highlight(next);
            } else if (event.key === "Escape") {
                event.preventDefault();
                closeResults();
            }
        });
        search.addEventListener("blur", function () { setTimeout(closeResults, 120); });

        if (copyToggle && copyBox) {
            copyToggle.addEventListener("click", function () {
                copyBox.hidden = !copyBox.hidden;
                if (!copyBox.hidden) {
                    copySearch.focus();
                    runCopySearch(copySearch.value);
                }
            });

            const runCopySearch = debounce(function (query) {
                getJSON(withQuery(root.dataset.copyUrl, {q: query}))
                    .then(function (data) {
                        copyResults.replaceChildren();
                        const products = data.products || [];
                        if (!products.length) {
                            const none = document.createElement("div");
                            none.className = "list-group-item text-muted small";
                            none.textContent = strings.strCopyEmpty || "";
                            copyResults.appendChild(none);
                        }
                        products.forEach(function (product) {
                            const button = document.createElement("button");
                            button.type = "button";
                            button.className = "list-group-item list-group-item-action d-flex justify-content-between align-items-center";
                            const name = document.createElement("span");
                            name.textContent = product.label;
                            const count = document.createElement("span");
                            count.className = "badge rounded-pill text-bg-secondary";
                            count.textContent = String(product.count);
                            button.append(name, count);
                            button.addEventListener("click", function () {
                                getJSON(withQuery(root.dataset.copyUrl, {product: product.id}))
                                    .then(function (payload) {
                                        addChips(payload.chips || []);
                                        copyBox.hidden = true;
                                        search.focus();
                                    });
                            });
                            copyResults.appendChild(button);
                        });
                    })
                    .catch(function () { copyResults.replaceChildren(); });
            }, 200);

            copySearch.addEventListener("input", function () { runCopySearch(copySearch.value); });
            copySearch.addEventListener("keydown", function (event) {
                if (event.key === "Enter") event.preventDefault();
            });
        }

        root.fitsPicker = {
            add: addChips,
            clear: function () { chips = []; renderChips(); sync(); },
            count: function () { return chips.length; },
        };
        renderChips();
    }

    function initAll(scope) {
        (scope || document).querySelectorAll("[data-fits-picker]").forEach(bind);
    }

    window.AutomotiveFitsPicker = {initAll: initAll, bind: bind};
    document.addEventListener("dlux:modal-content-loaded", function (event) { initAll(event.target); });
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { initAll(document); });
    }
    initAll(document);
})();
