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

// closeAttachmentModal() and MODAL_CONTAINER_DEFAULT_CLASS now live in
// global.js (loaded on every page, not just this one) — this used to be a
// page-scoped duplicate, which meant every OTHER page that can open the
// ticket slideover (most of them) had no closeAttachmentModal() at all,
// silently failing on both the modal's own X button and clicking its
// backdrop. See global.js's comment for the full explanation.

// ================================================================
// SCROLL TIMELINE TO BOTTOM / LIVE-POLL SWAP HANDLING
// ================================================================
// #commentTimeline polls itself every few seconds (see the hx-trigger in
// ticket_conversation.html) so an active back-and-forth shows the other
// person's replies without a manual refresh, and it's also the swap target
// when the compose form successfully posts. Both cases fire htmx:afterSwap
// on this same element, but they need very different handling:
//   - a poll swap must NEVER touch the composer — it previously did (this
//     listener used to assume the only thing that could ever swap
//     #commentTimeline was a successful send), which cleared out whatever
//     you were mid-typing every ~4 seconds even though nothing was sent.
//   - a send swap should reset the composer and always jump to the bottom.
//   - either kind of swap replaces the timeline's innerHTML, which would
//     otherwise reset scrollTop to 0 each time — stick to the bottom only
//     if the viewer was already near it (or hasn't scrolled at all), leave
//     their position alone if they've scrolled up to read history.
const TIMELINE_NEAR_BOTTOM_PX = 120;
let timelineStickToBottom = true;

function scrollTimelineToBottom() {
    const el = document.getElementById('commentTimeline');
    if (el) el.scrollTop = el.scrollHeight;
}

function isTimelineNearBottom() {
    const el = document.getElementById('commentTimeline');
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < TIMELINE_NEAR_BOTTOM_PX;
}

document.addEventListener('DOMContentLoaded', scrollTimelineToBottom);

document.addEventListener('scroll', function(evt) {
    if (evt.target && evt.target.id === 'commentTimeline') {
        timelineStickToBottom = isTimelineNearBottom();
    }
}, true);

// Set directly by #commentForm's own request lifecycle (htmx:beforeRequest
// fires on the element whose hx-post is driving the request — the form
// itself, unambiguously) rather than inferred from evt.detail.elt on the
// afterSwap event, which turned out not to reliably identify the form here.
let pendingSwapIsSend = false;
const commentFormEl = document.getElementById('commentForm');
if (commentFormEl) {
    commentFormEl.addEventListener('htmx:beforeRequest', function() {
        pendingSwapIsSend = true;
    });
}

document.body.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail.target && evt.detail.target.id === 'commentTimeline') {
        const wasSend = pendingSwapIsSend;
        pendingSwapIsSend = false;

        if (wasSend) {
            timelineStickToBottom = true;
        }
        if (timelineStickToBottom) {
            scrollTimelineToBottom();
        }

        const newTimeline = document.getElementById('commentTimeline');
        const inner = newTimeline ? newTimeline.querySelector('#timelineInner') : null;
        if (inner) {
            const newStatus = inner.getAttribute('data-status');
            if (newStatus) updateStatusChip(newStatus);
        }

        if (wasSend) {
            // The comment composer sits outside #commentTimeline, so nothing
            // else clears it after a successful send — reset it here. Never
            // do this on a poll swap — the viewer is very possibly mid-typing.
            const editor = document.getElementById('commentEditor');
            const hidden = document.getElementById('commentBodyHidden');
            if (editor) editor.innerHTML = '';
            if (hidden) hidden.value = '';
            if (window.resetAttachmentComposer) window.resetAttachmentComposer();
        }
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

    // The composer's own border color and a plain-language hint mirror
    // whichever mode is active, so which one you're in is obvious at a
    // glance — not just a small pill that's easy to miss, especially
    // since the toggle silently resets to Public on every page load.
    const editor = document.getElementById('commentEditor');
    const hint = document.getElementById('visibilityHint');

    if (mode === 'public') {
        publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
        internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
        const publicRadio = document.querySelector('input[value="PUBLIC"]');
        if (publicRadio) publicRadio.checked = true;
        if (editor) {
            editor.style.borderColor = 'var(--color-primary)';
            editor.dataset.placeholder = 'Write a reply…';
        }
        if (hint) hint.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path></svg> Visible to the requester';
    } else {
        internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
        publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
        const internalRadio = document.querySelector('input[value="INTERNAL"]');
        if (internalRadio) internalRadio.checked = true;
        if (editor) {
            editor.style.borderColor = 'var(--color-warning)';
            editor.dataset.placeholder = 'Write an internal note…';
        }
        if (hint) hint.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg> Team only — the requester will not see this';
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
// Shared staging/validation logic lives in global.js's
// createAttachmentComposer (also used by the Incident/Service Request
// submission forms) so all three attachment inputs behave identically.
(function() {
    if (!window.createAttachmentComposer) return;
    const composer = window.createAttachmentComposer('attachmentsInput', 'filePreviewContainer');
    if (!composer) return;

    // Exposed so the comment-send success handler can clear staged
    // attachments along with the rest of the composer.
    window.resetAttachmentComposer = composer.reset;
})();

// ================================================================
// MACROS
// ================================================================
function insertMacro(body, visibility) {
    const editor = document.getElementById('commentEditor');
    if (editor) {
        // Appended as its own block rather than replacing outright — picking
        // one macro into an empty composer makes it the only content;
        // picking another afterward stacks it below instead of erasing it.
        // Macro bodies are plain text (a Textarea field, no rich-text
        // sanitization on save) — build the block from text nodes/<br>
        // only, never innerHTML, so a macro can't inject markup/scripts
        // into every agent's composer that inserts it.
        const block = document.createElement('div');
        const lines = body.split('\n');
        lines.forEach((line, i) => {
            block.appendChild(document.createTextNode(line));
            if (i < lines.length - 1) block.appendChild(document.createElement('br'));
        });
        editor.appendChild(block);
        editor.focus();
        editor.dispatchEvent(new Event('input'));
        setActiveTab(visibility.toLowerCase());
        const radios = document.getElementsByName('visibility');
        for (let radio of radios) {
            if (radio.value === visibility) radio.checked = true;
        }
        if (window.closeMacroDropdown) {
            window.closeMacroDropdown();
        } else {
            const dropdown = document.getElementById('macroDropdown');
            if (dropdown) dropdown.classList.add('hidden');
        }
    }
}

// ================================================================
// INSERT KB ARTICLE
// ================================================================
function insertKbArticleLink(title, url) {
    const editor = document.getElementById('commentEditor');
    if (!editor) return;
    // Built from a real <a> element (not innerHTML) so a title containing
    // markup can't inject anything into the composer — same defensive
    // approach as insertMacro() above.
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = title;
    const block = document.createElement('div');
    block.appendChild(link);
    editor.appendChild(block);
    editor.focus();
    editor.dispatchEvent(new Event('input'));
    if (window.closeKbInsertDropdown) {
        window.closeKbInsertDropdown();
    } else {
        const dropdown = document.getElementById('kbInsertDropdown');
        if (dropdown) dropdown.classList.add('hidden');
    }
}

// Close macro dropdown on outside click
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('macroDropdown');
    const button = document.querySelector('[data-tooltip="Macros"]');
    if (dropdown && !dropdown.classList.contains('hidden') && !dropdown.contains(event.target) && button && !button.contains(event.target)) {
        // ticket_conversation.html defines closeMacroDropdown() to also
        // reset the trigger button's icon back from X — fall back to a
        // plain hide if some other page ever reuses #macroDropdown without it.
        if (window.closeMacroDropdown) {
            window.closeMacroDropdown();
        } else {
            dropdown.classList.add('hidden');
        }
    }
});

// ================================================================
// FULFILLMENT MODAL
// ================================================================
// openFulfillModal/closeFulfillModal moved to global.js so they're
// available on every page (e.g. the admin dashboard's Fulfill button),
// not just this ticket-conversation page.