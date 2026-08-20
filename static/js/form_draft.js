// static/js/form_draft.js
// Shared auto-save/manual-save draft support for the Incident and Service
// Request forms. Dual-layer: localStorage (instant, works fully offline)
// + best-effort server save (durable, cross-device). Restoring is always
// via an explicit banner prompt, never silent, per standard practice.

(function () {
    const DRAFT_VERSION = 'v1';

    function storageKey(ticketType) {
        return `draft_${ticketType}_${DRAFT_VERSION}`;
    }

    function getCsrfToken(form) {
        const input = form.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function serializeForm(form) {
        const data = {};
        const formData = new FormData(form);
        for (const [key, value] of formData.entries()) {
            const field = form.elements.namedItem(key);
            if (field && ((field.type === 'file') || (field.length !== undefined && field[0] && field[0].type === 'file'))) {
                continue; // file inputs can't be restored programmatically
            }
            if (key in data) {
                if (!Array.isArray(data[key])) data[key] = [data[key]];
                data[key].push(value);
            } else {
                data[key] = value;
            }
        }
        return data;
    }

    function restoreForm(form, data) {
        Object.keys(data).forEach(function (key) {
            const field = form.elements.namedItem(key);
            if (!field) return;
            const value = data[key];

            if (field instanceof RadioNodeList || (field.length !== undefined && !(field instanceof HTMLSelectElement))) {
                // Multiple inputs sharing a name (radio group, or a plain NodeList)
                const values = Array.isArray(value) ? value : [value];
                Array.from(field).forEach(function (el) {
                    if (el.type === 'checkbox' || el.type === 'radio') {
                        el.checked = values.includes(el.value);
                    } else {
                        el.value = values[0];
                    }
                });
                return;
            }

            if (field instanceof HTMLSelectElement && field.multiple) {
                const values = Array.isArray(value) ? value : [value];
                Array.from(field.options).forEach(function (opt) {
                    opt.selected = values.includes(opt.value);
                });
                return;
            }

            if (field.type === 'checkbox') {
                field.checked = value === 'on' || value === true;
                return;
            }

            field.value = Array.isArray(value) ? value[0] : value;
        });
    }

    function showBanner(form, savedAt, onRestore, onDiscard) {
        const existing = document.getElementById('draftRestoreBanner');
        if (existing) existing.remove();

        const banner = document.createElement('div');
        banner.id = 'draftRestoreBanner';
        banner.className = 'rounded-lg bg-primary/10 border border-primary/30 text-sm p-3 mb-4 flex items-center justify-between gap-3 flex-wrap';
        banner.innerHTML = `
            <span class="text-text-primary">
                You have a saved draft${savedAt ? ' from ' + savedAt : ''} — attachments aren't restored, so re-attach any files.
            </span>
            <span class="flex items-center gap-2 shrink-0">
                <button type="button" class="btn-primary text-xs px-3 py-1.5 rounded-lg" id="draftRestoreBtn">Restore</button>
                <button type="button" class="btn-ghost text-xs px-3 py-1.5 rounded-lg" id="draftDiscardBtn">Discard</button>
            </span>
        `;
        form.parentElement.insertBefore(banner, form);

        banner.querySelector('#draftRestoreBtn').addEventListener('click', function () {
            onRestore();
            banner.remove();
        });
        banner.querySelector('#draftDiscardBtn').addEventListener('click', function () {
            onDiscard();
            banner.remove();
        });
    }

    window.initFormDraft = function (options) {
        const form = options.form;
        const ticketType = options.ticketType;
        const onRestoreCallback = options.onRestore || function () {};
        const saveDraftBtn = options.saveDraftBtnId ? document.getElementById(options.saveDraftBtnId) : null;
        if (!form || !ticketType) return;

        const key = storageKey(ticketType);
        let debounceTimer = null;

        function saveToLocalStorage() {
            try {
                localStorage.setItem(key, JSON.stringify({ form_data: serializeForm(form), updated_at: new Date().toISOString() }));
            } catch (e) {
                // localStorage unavailable/full — server save below is still attempted
            }
        }

        function saveToServer(showConfirmation) {
            fetch('/tickets/draft/save/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(form) },
                body: JSON.stringify({ ticket_type: ticketType, form_data: serializeForm(form) }),
            }).then(function (res) {
                if (showConfirmation && res.ok && typeof showToast === 'function') {
                    showToast('Draft saved', 'success');
                }
            }).catch(function () {
                // Unstable network — localStorage already has it, retry next tick
            });
        }

        function saveDraft(manual) {
            saveToLocalStorage();
            saveToServer(manual === true);
        }

        function discardDraft() {
            try { localStorage.removeItem(key); } catch (e) {}
            fetch('/tickets/draft/discard/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(form) },
                body: JSON.stringify({ ticket_type: ticketType }),
            }).catch(function () {});
        }

        // ---- Offer restore (localStorage first — instant; server is the fallback) ----
        let localDraft = null;
        try {
            const raw = localStorage.getItem(key);
            if (raw) localDraft = JSON.parse(raw);
        } catch (e) {}

        function offerRestore(draft) {
            if (!draft || !draft.form_data || Object.keys(draft.form_data).length === 0) return;
            const savedAt = draft.updated_at ? new Date(draft.updated_at).toLocaleString() : '';
            showBanner(form, savedAt, function () {
                restoreForm(form, draft.form_data);
                onRestoreCallback(draft.form_data);
            }, discardDraft);
        }

        if (localDraft) {
            offerRestore(localDraft);
        } else {
            fetch(`/tickets/draft/get/?type=${ticketType}`)
                .then(function (res) { return res.status === 200 ? res.json() : null; })
                .then(offerRestore)
                .catch(function () {});
        }

        // ---- Auto-save: debounced on change, plus a periodic safety net ----
        form.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () { saveDraft(false); }, 2000);
        });
        form.addEventListener('change', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () { saveDraft(false); }, 2000);
        });
        setInterval(function () { saveDraft(false); }, 30000);

        // ---- Manual save ----
        if (saveDraftBtn) {
            saveDraftBtn.addEventListener('click', function () { saveDraft(true); });
        }
    };
})();
