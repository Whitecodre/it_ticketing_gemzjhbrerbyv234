// static/js/form_draft.js
// Shared auto-save/manual-save draft support for the Incident and Service
// Request forms. Dual-layer: localStorage (instant, works fully offline)
// + best-effort server save (durable, cross-device). Restoring is always
// via an explicit banner prompt, never silent, per standard practice.
//
// Attachments: a browser can never re-populate a file input on restore, so
// a picked file is uploaded to the draft the moment it's picked (see
// saveDraftAttachments below, wired via createAttachmentComposer's
// onFilesAdded) rather than waiting for the debounced field autosave.
// Restored files show as removable "(from draft)" chips and ride along at
// submit time via a hidden keep_draft_attachments field — see
// restore_kept_draft_attachments in apps/tickets/views.py for the other
// half of this.

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
            if (key === 'csrfmiddlewaretoken') {
                continue; // never persist/restore — the page's live token is always the valid one
            }
            const field = form.elements.namedItem(key);
            if (field && ((field.type === 'file') || (field.length !== undefined && field[0] && field[0].type === 'file'))) {
                continue; // file inputs can't be restored programmatically — handled separately, see above
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
            if (key === 'csrfmiddlewaretoken') return; // defense in depth for drafts saved before this fix
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

    function showBanner(form, savedAt, hasAttachments, onRestore, onDiscard) {
        const existing = document.getElementById('draftRestoreBanner');
        if (existing) existing.remove();

        const banner = document.createElement('div');
        banner.id = 'draftRestoreBanner';
        banner.className = 'rounded-lg bg-primary/10 border border-primary/30 text-sm p-3 mb-4 flex items-center justify-between gap-3 flex-wrap';
        banner.innerHTML = `
            <span class="text-text-primary">
                You have a saved draft${savedAt ? ' from ' + savedAt : ''}${hasAttachments ? ' — its attachments will be restored too' : ''}.
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

    // Mirrors freshly-picked files onto the server-side draft as they're
    // picked. Exposed globally so each form's own createAttachmentComposer
    // setup (in the template, initialized independently of initFormDraft
    // below) can wire it via opts.onFilesAdded without needing to share a
    // closure. These never end up in keep_draft_attachments — only restored
    // files the user hasn't removed do — so a fresh pick is never attached
    // twice (once live via the real submit, once via a stale draft copy).
    window.saveDraftAttachments = function (ticketType, files, form) {
        if (!files || !files.length) return;
        const formData = new FormData();
        formData.append('ticket_type', ticketType);
        files.forEach(function (f) { formData.append('attachments', f); });
        fetch('/tickets/draft/save-attachment/', {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken(form) },
            body: formData,
        }).catch(function () {
            // Best-effort — if this fails, the file still submits normally
            // via the live input this session, it just won't survive a
            // closed tab before then.
        });
    };

    window.initFormDraft = function (options) {
        const form = options.form;
        const ticketType = options.ticketType;
        const onRestoreCallback = options.onRestore || function () {};
        const saveDraftBtn = options.saveDraftBtnId ? document.getElementById(options.saveDraftBtnId) : null;
        const attachmentPreview = options.attachmentPreviewId ? document.getElementById(options.attachmentPreviewId) : null;
        if (!form || !ticketType) return;

        const key = storageKey(ticketType);
        let debounceTimer = null;

        // ---- Kept draft attachments (restored, not removed) — ride along
        // at submit via this hidden field. See restore_kept_draft_attachments
        // in views.py for how the server uses it. ----
        let keptAttachmentIds = [];
        const keepField = document.createElement('input');
        keepField.type = 'hidden';
        keepField.name = 'keep_draft_attachments';
        form.appendChild(keepField);
        function syncKeepField() { keepField.value = keptAttachmentIds.join(','); }

        function renderDraftAttachmentChip(att) {
            if (!attachmentPreview) return;
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs border max-w-full';
            chip.style.borderColor = 'var(--color-border)';
            chip.style.backgroundColor = 'var(--color-background)';
            chip.title = att.filename + ' — kept from your saved draft';
            chip.setAttribute('data-draft-chip', '1');

            const label = document.createElement('span');
            label.className = 'truncate';
            label.textContent = att.filename + ' (from draft)';
            chip.appendChild(label);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.textContent = '×';
            removeBtn.setAttribute('aria-label', 'Remove ' + att.filename);
            removeBtn.className = 'shrink-0 text-text-secondary hover:text-error font-bold leading-none';
            removeBtn.addEventListener('click', function () {
                keptAttachmentIds = keptAttachmentIds.filter(function (id) { return id !== att.id; });
                syncKeepField();
                chip.remove();
                fetch('/tickets/draft/discard-attachment/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(form) },
                    body: JSON.stringify({ attachment_id: att.id }),
                }).catch(function () {});
            });
            chip.appendChild(removeBtn);

            attachmentPreview.appendChild(chip);
        }

        function renderDraftAttachments(attachments) {
            (attachments || []).forEach(function (att) {
                keptAttachmentIds.push(att.id);
                renderDraftAttachmentChip(att);
            });
            syncKeepField();
        }

        function clearDraftAttachmentChips() {
            keptAttachmentIds = [];
            syncKeepField();
            if (attachmentPreview) {
                attachmentPreview.querySelectorAll('[data-draft-chip]').forEach(function (el) { el.remove(); });
            }
        }

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
            clearDraftAttachmentChips();
            fetch('/tickets/draft/discard/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(form) },
                body: JSON.stringify({ ticket_type: ticketType }),
            }).catch(function () {});
        }

        // ---- Offer restore (localStorage first for form fields — instant;
        // attachments only ever live server-side, so the server is always
        // checked regardless of whether localStorage had the fields). ----
        let localDraft = null;
        try {
            const raw = localStorage.getItem(key);
            if (raw) localDraft = JSON.parse(raw);
        } catch (e) {}

        function offerRestore(draft) {
            if (!draft) return;
            const hasFields = draft.form_data && Object.keys(draft.form_data).length > 0;
            const hasAttachments = draft.attachments && draft.attachments.length > 0;
            if (!hasFields && !hasAttachments) return;
            const savedAt = draft.updated_at ? new Date(draft.updated_at).toLocaleString() : '';
            showBanner(form, savedAt, hasAttachments, function () {
                if (hasFields) restoreForm(form, draft.form_data);
                renderDraftAttachments(draft.attachments);
                onRestoreCallback(draft.form_data || {});
            }, discardDraft);
        }

        fetch(`/tickets/draft/get/?type=${ticketType}`)
            .then(function (res) { return res.status === 200 ? res.json() : null; })
            .then(function (serverDraft) {
                if (localDraft) {
                    localDraft.attachments = serverDraft ? serverDraft.attachments : [];
                    offerRestore(localDraft);
                } else {
                    offerRestore(serverDraft);
                }
            })
            .catch(function () {
                if (localDraft) offerRestore(localDraft);
            });

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
