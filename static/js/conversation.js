// conversation.js – loaded only on the agent conversation page

// ================================================================
// DETAILS PANEL TOGGLE
// ================================================================
function toggleDetailsPanel() {
    const panel = document.getElementById('detailsPanel');
    if (!panel) return;
    if (window.innerWidth < 640) {
        panel.classList.toggle('w-0');
        panel.classList.toggle('w-full');
    } else {
        panel.classList.toggle('w-0');
        panel.classList.toggle('w-80');
        panel.classList.toggle('w-96');
    }
}

// ================================================================
// SUBJECT INLINE EDIT
// ================================================================
function toggleSubjectEdit() {
    const wrapper = document.getElementById('ticketTitleWrapper');
    if (!wrapper) return;
    const display = wrapper.querySelector('#subjectDisplay');
    const editBtn = wrapper.querySelector('button[onclick^="toggleSubjectEdit"]');
    const form = wrapper.querySelector('#subjectEditForm');
    if (!display || !form) return;
    const editing = !form.classList.contains('hidden');
    display.classList.toggle('hidden', !editing);
    if (editBtn) editBtn.classList.toggle('hidden', !editing);
    form.classList.toggle('hidden', editing);
    form.classList.toggle('flex', !editing);
    if (!editing) {
        const input = form.querySelector('input[name="title"]');
        if (input) { input.focus(); input.select(); }
    }
}

// ================================================================
// ATTACHMENT PREVIEW MODAL (open via inline onclick elsewhere; close here)
// ================================================================
function closeAttachmentModal() {
    const overlay = document.getElementById('modalOverlay');
    if (overlay) overlay.classList.add('hidden');
    const container = document.getElementById('modalContainer');
    if (container) container.innerHTML = '';
    document.body.style.overflow = '';
}

// ================================================================
// STATUS DROPDOWN
// ================================================================
function toggleStatusDropdown() {
    const menu = document.getElementById('statusMenu');
    const chevron = document.getElementById('statusChevron');
    if (!menu || !chevron) return;
    menu.classList.toggle('hidden');
    chevron.classList.toggle('rotate-180');
}

document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('statusDropdown');
    const menu = document.getElementById('statusMenu');
    const chevron = document.getElementById('statusChevron');
    if (dropdown && menu && !dropdown.contains(event.target)) {
        menu.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
});

// ================================================================
// SCROLL TIMELINE TO BOTTOM
// ================================================================
function scrollTimelineToBottom() {
    const el = document.getElementById('commentTimeline');
    if (el) el.scrollTop = el.scrollHeight;
}

document.addEventListener('DOMContentLoaded', scrollTimelineToBottom);

document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target && evt.detail.target.id === 'commentTimeline') {
        scrollTimelineToBottom();
        const newTimeline = document.getElementById('commentTimeline');
        const inner = newTimeline ? newTimeline.querySelector('#timelineInner') : null;
        if (inner) {
            const newStatus = inner.getAttribute('data-status');
            if (newStatus) updateStatusChip(newStatus);
        }
        // The comment composer sits outside #commentTimeline, so nothing
        // else clears it after a successful send — reset it here.
        const editor = document.getElementById('commentEditor');
        const hidden = document.getElementById('commentBodyHidden');
        if (editor) editor.innerHTML = '';
        if (hidden) hidden.value = '';
        if (window.resetAttachmentComposer) window.resetAttachmentComposer();
    }
});

// ================================================================
// UPDATE STATUS CHIP
// ================================================================
function updateStatusChip(status) {
    const chipContainer = document.getElementById('ticketStatusChip');
    if (!chipContainer) return;
    const statusMap = {
        'NEW': { cls: 'open', text: 'New' },
        'TRIAGED': { cls: 'open', text: 'Triaged' },
        'ASSIGNED': { cls: 'in-progress', text: 'Assigned' },
        'IN_PROGRESS': { cls: 'in-progress', text: 'In Progress' },
        'PENDING_USER': { cls: 'open', text: 'Pending User' },
        'PENDING_VENDOR': { cls: 'open', text: 'Pending Vendor' },
        'PENDING_FULFILLMENT': { cls: 'pending-approval', text: 'Pending Fulfillment' },
        'RESOLVED': { cls: 'resolved', text: 'Resolved' },
        'CLOSED': { cls: 'resolved', text: 'Closed' },
        'APPROVED': { cls: 'approved', text: 'Approved' },
        'ESCALATED': { cls: 'escalated', text: 'Escalated' },
    };
    const info = statusMap[status] || { cls: 'open', text: status };
    chipContainer.innerHTML = `<span class="status-chip ${info.cls} text-xs">${info.text}</span>`;
}

// ================================================================
// ACTIVE TAB FOR PUBLIC/INTERNAL
// ================================================================
function setActiveTab(mode) {
    const publicSpan = document.getElementById('tabPublic');
    const internalSpan = document.getElementById('tabInternal');
    if (!publicSpan || !internalSpan) return;
    
    if (mode === 'public') {
        publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
        internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
        const publicRadio = document.querySelector('input[value="PUBLIC"]');
        if (publicRadio) publicRadio.checked = true;
    } else {
        internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
        publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
        const internalRadio = document.querySelector('input[value="INTERNAL"]');
        if (internalRadio) internalRadio.checked = true;
    }
}

// ================================================================
// COMMENT EDITOR -> HIDDEN FIELD SYNC
// ================================================================
// #commentEditor is a contenteditable div; the form actually submits
// #commentBodyHidden. Keep it in sync on every keystroke so HTMX always
// serializes the current content, regardless of event ordering.
(function() {
    const editor = document.getElementById('commentEditor');
    const hidden = document.getElementById('commentBodyHidden');
    if (!editor || !hidden) return;

    function syncCommentBody() {
        hidden.value = editor.innerHTML.trim();
    }

    editor.addEventListener('input', syncCommentBody);

    const form = document.getElementById('commentForm');
    if (form) {
        form.addEventListener('submit', syncCommentBody);
        form.addEventListener('htmx:configRequest', syncCommentBody);
    }
})();

// ================================================================
// BOLD / ITALIC FORMATTING
// ================================================================
function formatDocument(command) {
    const editor = document.getElementById('commentEditor');
    if (!editor) return;
    editor.focus();
    document.execCommand(command, false, null);
}

// ================================================================
// ATTACHMENT PREVIEW
// ================================================================
(function() {
    const input = document.getElementById('attachmentsInput');
    const preview = document.getElementById('filePreviewContainer');
    if (!input || !preview) return;

    // Staged files persist across multiple picker openings (native
    // multi-file inputs replace the whole FileList on every dialog use),
    // and each chip gets its own remove button so a single mis-added file
    // doesn't force starting the whole selection over.
    let stagedFiles = [];

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function syncInputFiles() {
        const dt = new DataTransfer();
        stagedFiles.forEach(function(f) { dt.items.add(f); });
        input.files = dt.files;
    }

    function renderChips() {
        preview.innerHTML = '';
        stagedFiles.forEach(function(file, index) {
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs border';
            chip.style.borderColor = 'var(--color-border)';
            chip.style.backgroundColor = 'var(--color-background)';

            const label = document.createElement('span');
            label.textContent = `${file.name} (${formatFileSize(file.size)})`;
            chip.appendChild(label);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.textContent = '×';
            removeBtn.setAttribute('aria-label', `Remove ${file.name}`);
            removeBtn.className = 'text-text-secondary hover:text-error font-bold leading-none';
            removeBtn.addEventListener('click', function() {
                stagedFiles.splice(index, 1);
                syncInputFiles();
                renderChips();
            });
            chip.appendChild(removeBtn);

            preview.appendChild(chip);
        });
    }

    input.addEventListener('change', function() {
        stagedFiles = stagedFiles.concat(Array.from(input.files || []));
        syncInputFiles();
        renderChips();
    });

    // Exposed so the comment-send success handler can clear staged
    // attachments along with the rest of the composer.
    window.resetAttachmentComposer = function() {
        stagedFiles = [];
        preview.innerHTML = '';
        input.value = '';
    };
})();

// ================================================================
// MACROS
// ================================================================
function insertMacro(body, visibility) {
    const editor = document.getElementById('commentEditor');
    if (editor) {
        editor.innerHTML = body;
        editor.dispatchEvent(new Event('input'));
        setActiveTab(visibility.toLowerCase());
        const radios = document.getElementsByName('visibility');
        for (let radio of radios) {
            if (radio.value === visibility) radio.checked = true;
        }
        const dropdown = document.getElementById('macroDropdown');
        if (dropdown) dropdown.classList.add('hidden');
    }
}

// Close macro dropdown on outside click
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('macroDropdown');
    const button = document.querySelector('[data-tooltip="Macros"]');
    if (dropdown && !dropdown.classList.contains('hidden') && !dropdown.contains(event.target) && button && !button.contains(event.target)) {
        dropdown.classList.add('hidden');
    }
});

// ================================================================
// FULFILLMENT MODAL
// ================================================================
// openFulfillModal/closeFulfillModal moved to global.js so they're
// available on every page (e.g. the admin dashboard's Fulfill button),
// not just this ticket-conversation page.