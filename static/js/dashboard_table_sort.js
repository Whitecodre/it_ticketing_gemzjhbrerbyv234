// Generic client-side column sorting for dashboard ticket tables.
// A table opts in with data-sortable="true"; sortable headers carry
// data-sort-key, and each cell in that column carries data-value
// (the raw value to compare, since displayed text is often formatted).
(function() {
    var NUMERIC_RE = /^-?\d+(\.\d+)?$/;

    function initSortableTable(table) {
        if (!table || table.dataset.sortInit === '1') return;
        table.dataset.sortInit = '1';

        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th[data-sort-key]');
        if (!tbody || !headers.length) return;

        var state = { key: null, dir: 1 };

        headers.forEach(function(th) {
            th.classList.add('cursor-pointer', 'select-none');
            th.setAttribute('role', 'button');
            th.setAttribute('tabindex', '0');

            var indicator = document.createElement('span');
            indicator.className = 'sort-indicator ml-1 inline-block text-[0.65rem] opacity-40';
            indicator.textContent = '⇅';
            th.appendChild(indicator);

            function sortByThisHeader() {
                var key = th.dataset.sortKey;
                var colIndex = Array.prototype.indexOf.call(th.parentElement.children, th);

                state.dir = (state.key === key) ? state.dir * -1 : 1;
                state.key = key;

                headers.forEach(function(h) {
                    var ind = h.querySelector('.sort-indicator');
                    if (ind) ind.textContent = '⇅';
                });
                indicator.textContent = state.dir === 1 ? '↑' : '↓';
                indicator.classList.remove('opacity-40');

                var rows = Array.prototype.slice.call(tbody.children).filter(function(row) {
                    return row.children[colIndex] !== undefined && row.dataset.ticketId;
                });
                if (!rows.length) return;

                rows.sort(function(a, b) {
                    var av = a.children[colIndex].dataset.value || '';
                    var bv = b.children[colIndex].dataset.value || '';
                    var cmp;
                    if (NUMERIC_RE.test(av.trim()) && NUMERIC_RE.test(bv.trim())) {
                        cmp = parseFloat(av) - parseFloat(bv);
                    } else {
                        cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
                    }
                    return cmp * state.dir;
                });

                rows.forEach(function(row) { tbody.appendChild(row); });
            }

            th.addEventListener('click', sortByThisHeader);
            th.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    sortByThisHeader();
                }
            });
        });
    }

    function initAll(root) {
        (root || document).querySelectorAll('table[data-sortable="true"]').forEach(initSortableTable);
    }

    window.initSortableTable = initSortableTable;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { initAll(document); });
    } else {
        initAll(document);
    }

    // Re-init after HTMX swaps a table back in (sortInit flag resets so
    // freshly-swapped markup gets its listeners re-attached).
    document.addEventListener('htmx:afterSwap', function(e) {
        if (!e.target || !e.target.querySelectorAll) return;
        e.target.querySelectorAll('table[data-sortable="true"]').forEach(function(t) {
            t.dataset.sortInit = '';
            initSortableTable(t);
        });
    });
})();
