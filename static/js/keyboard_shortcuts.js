document.addEventListener('keydown', function(e) {
    const target = e.target;
    const isCtrl = e.ctrlKey || e.metaKey;

    // Rich text shortcuts: Ctrl+B (bold), Ctrl+I (italic)
    if (isCtrl && (e.key === 'b' || e.key === 'i')) {
        // Check if focus is inside a contenteditable div
        const active = document.activeElement;
        const isInEditor = active && (active.isContentEditable || active.closest('[contenteditable="true"]'));
        if (isInEditor) {
            e.preventDefault();
            const command = e.key === 'b' ? 'bold' : 'italic';
            if (typeof formatDocument === 'function') {
                formatDocument(command);
            } else {
                document.execCommand(command, false, null);
            }
            return;
        }
    }

    // Enter sends the comment (standard chat-app convention — WhatsApp,
    // Slack, etc.); Shift+Enter inserts a newline instead (contenteditable's
    // own default behavior, so that case needs no code here at all — just
    // not intercepting it). Ctrl/Cmd+Enter also newlines, for anyone whose
    // muscle memory expects that from other apps.
    if (e.key === 'Enter' && !e.shiftKey && !isCtrl && !e.isComposing) {
        const editor = document.getElementById('commentEditor');
        if (editor && (target === editor || editor.contains(target))) {
            e.preventDefault();
            if (editor.textContent.trim() === '') return; // nothing to send
            const form = document.getElementById('commentForm');
            // The form already syncs #commentBodyHidden from the editor on
            // its own 'submit' event (see conversation.js) — dispatching a
            // real submit event here triggers that same listener, same as
            // clicking the Send button would.
            if (form) form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
            return;
        }
    }

    // Don't interfere with other inputs
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
    }

    // Esc, J/K, Enter for table navigation (unchanged)
    if (e.key === 'Escape') {
        if (typeof closeSlideover === 'function') closeSlideover();
        closeDetailsPanelIfOpen();
        closeStatusMenuIfOpen();
    }

    if (document.querySelector('.ticket-checkbox') && (e.key === 'j' || e.key === 'k')) {
        e.preventDefault();
        const rows = Array.from(document.querySelectorAll('tr.group'));
        if (rows.length === 0) return;
        let currentIdx = rows.findIndex(r => r.classList.contains('highlighted-row'));
        if (currentIdx === -1) currentIdx = 0;
        rows.forEach(r => r.classList.remove('highlighted-row'));
        if (e.key === 'j') currentIdx = (currentIdx + 1) % rows.length;
        else currentIdx = (currentIdx - 1 + rows.length) % rows.length;
        rows[currentIdx].classList.add('highlighted-row');
        rows[currentIdx].scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }

    if (e.key === 'Enter' && document.querySelector('.ticket-checkbox')) {
        const highlighted = document.querySelector('.highlighted-row');
        if (highlighted) {
            e.preventDefault();
            const viewLink = highlighted.querySelector('a[href*="conversation"], a[href*="slideover"]');
            if (viewLink) {
                if (viewLink.getAttribute('hx-get')) viewLink.click();
                else window.location.href = viewLink.href;
            }
        }
    }
});

function closeDetailsPanelIfOpen() {
    const panel = document.getElementById('detailsPanel');
    if (panel && typeof toggleDetailsPanel === 'function') {
        if (!panel.classList.contains('hidden') && !panel.classList.contains('w-0')) {
            toggleDetailsPanel();
        }
    }
}

function closeStatusMenuIfOpen() {
    const menu = document.getElementById('statusMenu');
    const chevron = document.getElementById('statusChevron');
    if (menu && !menu.classList.contains('hidden')) {
        menu.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
}
