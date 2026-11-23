(function () {
    function ready(fn) {
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
        else fn();
    }

    ready(function () {
        const root = document.querySelector('[data-workspace-dashboard]');
        if (!root) return;
        const grid = root.querySelector('[data-dashboard-grid]');
        if (!grid) return;
        const storageKey = root.dataset.storageKey || 'sales_crm.workspace.dashboard.v1';
        const appPrefNamespace = root.dataset.appPrefNamespace || 'sales_crm.workspace_dashboard.v1';
        const appPrefUrlTemplate = root.dataset.appPrefUrlTemplate || '';
        const sizeOrder = ['s', 'm', 'l', 'xl'];
        const originalOrder = Array.from(grid.querySelectorAll('[data-widget-id]')).map((tile) => tile.dataset.widgetId);

        function isState(value) {
            return value && typeof value === 'object' && !Array.isArray(value);
        }

        function readLocalState() {
            try {
                const state = JSON.parse(localStorage.getItem(storageKey) || 'null');
                return isState(state) ? state : null;
            } catch (err) {
                return null;
            }
        }

        function readAppState() {
            if (typeof window.getAppPreference === 'function') {
                const state = window.getAppPreference(appPrefNamespace, null);
                return isState(state) ? state : null;
            }
            const appPrefs = window.USER_PREFS && window.USER_PREFS.app;
            const state = appPrefs && appPrefs[appPrefNamespace];
            return isState(state) ? state : null;
        }

        function csrfToken() {
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? meta.getAttribute('content') : '';
        }

        function appPrefUrl() {
            if (appPrefUrlTemplate && appPrefUrlTemplate.includes('__namespace__')) {
                return appPrefUrlTemplate.replace('__namespace__', encodeURIComponent(appPrefNamespace));
            }
            return '';
        }

        function syncAppPrefCache(value) {
            if (!window.USER_PREFS) return;
            if (!window.USER_PREFS.app || typeof window.USER_PREFS.app !== 'object') {
                window.USER_PREFS.app = {};
            }
            if (value === null || value === undefined) delete window.USER_PREFS.app[appPrefNamespace];
            else window.USER_PREFS.app[appPrefNamespace] = value;
        }

        function persistAppState(state) {
            const token = csrfToken();
            const url = appPrefUrl();
            if (url && token) {
                fetch(url, {
                    method: 'POST',
                    headers: {'X-CSRFToken': token, 'Content-Type': 'application/json'},
                    body: JSON.stringify(state === undefined ? null : state),
                }).then(function (response) {
                    if (response.ok) syncAppPrefCache(state);
                }).catch(function () {});
                return;
            }
            if (typeof window.updateAppPreference === 'function') {
                window.updateAppPreference(appPrefNamespace, state).catch(function () {});
            }
        }

        function loadState() {
            const appState = readAppState();
            if (appState) return appState;

            if (appPrefUrl() || (window.USER_PREFS && typeof window.USER_PREFS === 'object')) {
                try { localStorage.removeItem(storageKey); } catch (err) {}
                return {};
            }

            const localState = readLocalState();
            if (localState) {
                // One-time migration from the pre-1.4.2 browser-only layout.
                persistAppState(localState);
                return localState;
            }
            return {};
        }

        function writeState(state) {
            try {
                localStorage.setItem(storageKey, JSON.stringify(state));
            } catch (err) {
                // Browser storage can be disabled; dlux app preferences remain primary.
            }
            persistAppState(state);
        }

        function tiles() {
            return Array.from(grid.querySelectorAll('[data-widget-id]'));
        }

        function currentState() {
            const state = {order: [], hidden: [], sizes: {}};
            tiles().forEach((tile) => {
                const id = tile.dataset.widgetId;
                state.order.push(id);
                if (tile.hidden) state.hidden.push(id);
                state.sizes[id] = tile.dataset.size || tile.dataset.defaultSize || 'm';
            });
            return state;
        }

        function saveState() {
            writeState(currentState());
        }

        function syncToggles() {
            root.querySelectorAll('[data-dashboard-toggle]').forEach((input) => {
                const tile = grid.querySelector('[data-widget-id="' + input.dataset.dashboardToggle + '"]');
                input.checked = !!tile && !tile.hidden;
            });
        }

        function applyState() {
            const state = loadState();
            const byId = new Map(tiles().map((tile) => [tile.dataset.widgetId, tile]));
            const orderedIds = Array.isArray(state.order) ? state.order : [];
            orderedIds.forEach((id) => {
                const tile = byId.get(id);
                if (tile) grid.appendChild(tile);
            });
            originalOrder.forEach((id) => {
                const tile = byId.get(id);
                if (tile && !orderedIds.includes(id)) grid.appendChild(tile);
            });

            const hidden = new Set(Array.isArray(state.hidden) ? state.hidden : []);
            const sizes = state.sizes && typeof state.sizes === 'object' ? state.sizes : {};
            tiles().forEach((tile) => {
                const id = tile.dataset.widgetId;
                tile.hidden = hidden.has(id);
                const size = sizeOrder.includes(sizes[id]) ? sizes[id] : (tile.dataset.defaultSize || 'm');
                tile.dataset.size = size;
            });
            syncToggles();
        }

        function cycleSize(tile) {
            const current = tile.dataset.size || tile.dataset.defaultSize || 'm';
            const idx = sizeOrder.indexOf(current);
            tile.dataset.size = sizeOrder[(idx + 1 + sizeOrder.length) % sizeOrder.length];
            saveState();
        }

        function setVisible(id, visible) {
            const tile = grid.querySelector('[data-widget-id="' + id + '"]');
            if (!tile) return;
            tile.hidden = !visible;
            syncToggles();
            saveState();
        }

        root.addEventListener('click', function (event) {
            const customize = event.target.closest('[data-dashboard-customize]');
            if (customize) {
                const drawer = root.querySelector('[data-dashboard-drawer]');
                const open = drawer.hasAttribute('hidden');
                drawer.toggleAttribute('hidden', !open);
                customize.setAttribute('aria-expanded', open ? 'true' : 'false');
                return;
            }

            const sizeButton = event.target.closest('[data-dashboard-size]');
            if (sizeButton) {
                const tile = sizeButton.closest('[data-widget-id]');
                if (tile) cycleSize(tile);
                return;
            }

            const hideButton = event.target.closest('[data-dashboard-hide]');
            if (hideButton) {
                const tile = hideButton.closest('[data-widget-id]');
                if (tile) setVisible(tile.dataset.widgetId, false);
            }
        });

        root.addEventListener('change', function (event) {
            const input = event.target.closest('[data-dashboard-toggle]');
            if (!input) return;
            setVisible(input.dataset.dashboardToggle, input.checked);
        });

        let dragged = null;
        grid.addEventListener('dragstart', function (event) {
            const tile = event.target.closest('[data-widget-id]');
            const interactive = event.target.closest('a, button, input, label');
            if (!tile || (interactive && !event.target.closest('[data-dashboard-drag]'))) {
                event.preventDefault();
                return;
            }
            dragged = tile;
            tile.classList.add('is-dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', tile.dataset.widgetId);
        });

        grid.addEventListener('dragover', function (event) {
            if (!dragged) return;
            event.preventDefault();
            const target = event.target.closest('[data-widget-id]');
            if (!target || target === dragged || target.hidden) return;
            tiles().forEach((tile) => tile.classList.remove('drag-target'));
            target.classList.add('drag-target');
            const box = target.getBoundingClientRect();
            const after = event.clientY > box.top + box.height / 2 || event.clientX > box.left + box.width / 2;
            grid.insertBefore(dragged, after ? target.nextSibling : target);
        });

        grid.addEventListener('dragend', function () {
            if (dragged) dragged.classList.remove('is-dragging');
            tiles().forEach((tile) => tile.classList.remove('drag-target'));
            dragged = null;
            saveState();
        });

        applyState();
    });
})();
