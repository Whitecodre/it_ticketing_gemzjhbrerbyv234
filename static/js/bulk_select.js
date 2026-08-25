// ================================================================
// SHARED BULK-SELECT STATE — one Alpine component reused by every
// table that needs header-checkbox + per-row-checkbox + a bulk action
// bar, instead of each table hand-rolling its own selection JS.
//
// Usage (wrap the table + bulk bar in one element):
//   <div x-data="bulkSelect()">
//     <div x-show="count > 0" x-cloak> ...bar, x-text="count"... </div>
//     <input type="checkbox" x-model="allSelected" @change="toggleAll($event.target.checked)">
//     ...
//     <input type="checkbox" class="bulk-row-checkbox" value="{{ id }}"
//            :checked="selected.includes('{{ id }}')"
//            @change="toggleRow('{{ id }}', $event.target.checked)">
//
// Row checkboxes are found via the `.bulk-row-checkbox` class scoped to
// the x-data element (`this.$el`), so multiple independent bulkSelect()
// instances can coexist on one page without colliding.
// ================================================================
document.addEventListener('alpine:init', function () {
    Alpine.data('bulkSelect', function () {
        return {
            selected: [],

            get count() {
                return this.selected.length;
            },

            get allSelected() {
                // $root (not $el) — $el resolves to whichever element the
                // calling directive is written on (e.g. the header checkbox
                // itself, which has no row children), while $root always
                // resolves to this x-data host regardless of which
                // descendant triggered the evaluation.
                var boxes = this.$root.querySelectorAll('.bulk-row-checkbox');
                return boxes.length > 0 && this.selected.length === boxes.length;
            },

            toggleAll: function (checked) {
                var boxes = this.$root.querySelectorAll('.bulk-row-checkbox');
                this.selected = checked ? Array.from(boxes).map(function (cb) { return cb.value; }) : [];
            },

            toggleRow: function (value, checked) {
                if (checked) {
                    if (this.selected.indexOf(value) === -1) this.selected.push(value);
                } else {
                    this.selected = this.selected.filter(function (v) { return v !== value; });
                }
            },

            clear: function () {
                this.selected = [];
            },

            // Call after an HTMX swap replaces the rows (filter/pagination) —
            // the old selection no longer corresponds to any checkbox on
            // the page.
            reset: function () {
                this.selected = [];
            },
        };
    });
});
