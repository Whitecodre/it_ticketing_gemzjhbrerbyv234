// static/js/searchable_select.js
// Reusable Alpine.js searchable multi-select / combobox for admin-curated
// lists that can grow arbitrarily long (Vessels, Dive Systems, Job Numbers).
// Keeps real hidden inputs in sync with Alpine state so the exact same
// name/value contract the server already reads is preserved — no Django
// form/view changes needed.
//
// Usage (see templates/requester/service_request_form.html):
//   x-data="searchableSelect({
//       mode: 'multi' | 'single-create',
//       fieldName: 'vessels',
//       options: [{id: '1', label: 'MV Explorer'}, ...],
//       initialSelected: ['1', '2'],           // multi mode
//       initialSelectedId: '', initialNewText: '',  // single-create mode
//       placeholder: 'Search vessels…',
//   })"
//
// Optional group filter (multi mode): give options a `group` value
// (e.g. a department code) and bind a <select> to `groupFilter` — see
// templates/documents_display/document_share.html for an example. Options
// with no `group` always match, so this is a no-op for callers that don't
// use it.

document.addEventListener('alpine:init', () => {
    Alpine.data('searchableSelect', (config) => ({
        mode: config.mode || 'multi',
        fieldName: config.fieldName,
        options: config.options || [],
        placeholder: config.placeholder || 'Search…',
        query: '',
        open: false,

        // multi mode
        selected: (config.initialSelected || []).slice(),
        groupFilter: '',

        // single-create mode
        selectedId: config.initialSelectedId || '',
        newText: config.initialNewText || '',

        init() {
            if (this.mode === 'single-create') {
                if (this.selectedId === 'NEW') {
                    this.query = this.newText;
                } else if (this.selectedId) {
                    const match = this.options.find((o) => o.id === this.selectedId);
                    if (match) this.query = match.label;
                }
            }
        },

        get filtered() {
            const q = this.query.trim().toLowerCase();
            let list = this.options;
            if (this.mode === 'multi') {
                list = list.filter((o) => !this.selected.includes(o.id));
                if (this.groupFilter) {
                    list = list.filter((o) => o.group === this.groupFilter);
                }
            }
            if (!q) return list;
            return list.filter((o) => o.label.toLowerCase().includes(q));
        },

        get showCreateRow() {
            if (this.mode !== 'single-create') return false;
            const q = this.query.trim();
            if (!q) return false;
            return !this.options.some((o) => o.label.toLowerCase() === q.toLowerCase());
        },

        labelFor(id) {
            const match = this.options.find((o) => o.id === id);
            return match ? match.label : id;
        },

        toggle(id) {
            if (this.mode !== 'multi') return;
            if (this.selected.includes(id)) {
                this.selected = this.selected.filter((x) => x !== id);
            } else {
                this.selected = this.selected.concat([id]);
            }
            this.query = '';
            this.open = false;
        },

        remove(id) {
            if (this.mode !== 'multi') return;
            this.selected = this.selected.filter((x) => x !== id);
        },

        selectSingle(id) {
            this.selectedId = id;
            this.newText = '';
            this.query = this.labelFor(id);
            this.open = false;
        },

        createNew() {
            const text = this.query.trim();
            if (!text) return;
            this.selectedId = 'NEW';
            this.newText = text;
            this.open = false;
        },

        clearSingle() {
            this.selectedId = '';
            this.newText = '';
            this.query = '';
            this.open = true;
            this.$refs.searchInput && this.$refs.searchInput.focus();
        },
    }));
});
