// static/js/kb_editor_src.js
// Source for the KB article content editor. Bundled to static/js/kb_editor.js
// via `npm run build-kb-editor` (esbuild) — this repo has no bundler wired
// into the request/response cycle, so TipTap is vendored as a single local
// build artifact rather than fetched from a CDN at runtime (see CLAUDE.md's
// note on not reintroducing npm-managed frontend deps without confirming;
// vendoring a built file, with no live CDN dependency, is the safer form of
// that vs. re-adding a runtime dependency on a third-party host being up).
// Re-run the build whenever this file changes — the shipped kb_editor.js is
// the actual artifact loaded by templates, not this file.
//
// This is the single editor used for all KB article authoring, including
// ticket-conversion drafts (a separate TinyMCE-based form previously existed
// only for that flow — removed in favor of routing everything through here).

import { Editor, Node, mergeAttributes } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import Image from '@tiptap/extension-image';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TextAlign from '@tiptap/extension-text-align';

const ACTIVE_CLASSES = ['bg-primary/10', 'text-primary'];

// A simple note/callout box — its own block node (not just a styled
// blockquote) so it round-trips through content|table parsing cleanly and
// survives apps/knowledge_base/sanitize.py's allowlist (div.kb-callout).
const Callout = Node.create({
    name: 'callout',
    group: 'block',
    content: 'block+',
    defining: true,
    parseHTML() {
        return [{ tag: 'div.kb-callout' }];
    },
    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { class: 'kb-callout' }), 0];
    },
});

function uploadImage(file, uploadUrl, csrfToken) {
    const formData = new FormData();
    formData.append('image', file);
    return fetch(uploadUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        body: formData,
    }).then((res) => res.json().then((data) => ({ ok: res.ok, data })));
}

export function mountKbEditor({ mountId, toolbarId, hiddenFieldId, initialContent, outlineId, tableControlsId, imageUploadUrl, csrfToken, onDirtyChange }) {
    const mountEl = document.getElementById(mountId);
    const toolbarEl = document.getElementById(toolbarId);
    const hiddenField = document.getElementById(hiddenFieldId);
    const outlineEl = outlineId ? document.getElementById(outlineId) : null;
    const tableControlsEl = tableControlsId ? document.getElementById(tableControlsId) : null;
    if (!mountEl || !toolbarEl || !hiddenField) return null;

    const editor = new Editor({
        element: mountEl,
        extensions: [
            StarterKit,
            Link.configure({ openOnClick: false }),
            Image,
            Table.configure({ resizable: false }),
            TableRow,
            TableCell,
            TableHeader,
            Callout,
            TextAlign.configure({ types: ['heading', 'paragraph'] }),
        ],
        content: initialContent || '',
        editorProps: {
            attributes: {
                class: 'kb-editor-content prose max-w-none text-sm text-text-primary focus:outline-none',
            },
        },
        onUpdate({ editor }) {
            hiddenField.value = editor.getHTML();
            renderOutline();
            if (typeof onDirtyChange === 'function') onDirtyChange(true);
        },
        onTransaction() {
            renderToolbarState();
            renderTableControls();
        },
    });

    hiddenField.value = editor.getHTML();

    // Hidden file input driving the image toolbar button — replaces the old
    // window.prompt('Image URL') flow with a real upload.
    let fileInput = null;
    if (imageUploadUrl) {
        fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = 'image/png,image/jpeg,image/gif,image/webp';
        fileInput.style.display = 'none';
        fileInput.addEventListener('change', () => {
            const file = fileInput.files[0];
            fileInput.value = '';
            if (file) insertUploadedImage(file);
        });
        mountEl.parentElement.appendChild(fileInput);

        // Paste/drop a real image file — uploads instead of inlining base64.
        mountEl.addEventListener('paste', (e) => {
            const file = Array.from(e.clipboardData?.files || []).find((f) => f.type.startsWith('image/'));
            if (file) {
                e.preventDefault();
                insertUploadedImage(file);
            }
        });
        mountEl.addEventListener('drop', (e) => {
            const file = Array.from(e.dataTransfer?.files || []).find((f) => f.type.startsWith('image/'));
            if (file) {
                e.preventDefault();
                insertUploadedImage(file);
            }
        });
    }

    function insertUploadedImage(file) {
        uploadImage(file, imageUploadUrl, csrfToken).then(({ ok, data }) => {
            if (ok && data.url) {
                editor.chain().focus().setImage({ src: data.url, alt: data.alt || '' }).run();
            } else if (typeof showToast === 'function') {
                showToast(data.error || 'Image upload failed', 'error');
            }
        }).catch(() => {
            if (typeof showToast === 'function') showToast('Image upload failed', 'error');
        });
    }

    const actions = {
        bold: () => editor.chain().focus().toggleBold().run(),
        italic: () => editor.chain().focus().toggleItalic().run(),
        code: () => editor.chain().focus().toggleCode().run(),
        codeBlock: () => editor.chain().focus().toggleCodeBlock().run(),
        blockquote: () => editor.chain().focus().toggleBlockquote().run(),
        bulletList: () => editor.chain().focus().toggleBulletList().run(),
        orderedList: () => editor.chain().focus().toggleOrderedList().run(),
        undo: () => editor.chain().focus().undo().run(),
        redo: () => editor.chain().focus().redo().run(),
        link: () => {
            const previousUrl = editor.getAttributes('link').href;
            const url = window.prompt('Link URL', previousUrl || 'https://');
            if (url === null) return;
            if (url === '') {
                editor.chain().focus().extendMarkRange('link').unsetLink().run();
                return;
            }
            editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
        },
        image: () => {
            if (fileInput) {
                fileInput.click();
            } else {
                const url = window.prompt('Image URL');
                if (!url) return;
                editor.chain().focus().setImage({ src: url }).run();
            }
        },
        table: () => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
        addRowAfter: () => editor.chain().focus().addRowAfter().run(),
        addColumnAfter: () => editor.chain().focus().addColumnAfter().run(),
        deleteRow: () => editor.chain().focus().deleteRow().run(),
        deleteColumn: () => editor.chain().focus().deleteColumn().run(),
        deleteTable: () => editor.chain().focus().deleteTable().run(),
        alignLeft: () => editor.chain().focus().setTextAlign('left').run(),
        alignCenter: () => editor.chain().focus().setTextAlign('center').run(),
        alignRight: () => editor.chain().focus().setTextAlign('right').run(),
        callout: () => editor.chain().focus().insertContent({
            type: 'callout',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Note: ' }] }],
        }).run(),
    };

    // Only toggles the active-state classes on top of whatever resting
    // classes the template already put on each button — avoids rebuilding
    // (and thus briefly blanking) the whole className on every transaction.
    function renderToolbarState() {
        toolbarEl.querySelectorAll('[data-action]').forEach((btn) => {
            const action = btn.dataset.action;
            let active = false;
            if (action === 'bold') active = editor.isActive('bold');
            else if (action === 'italic') active = editor.isActive('italic');
            else if (action === 'code') active = editor.isActive('code');
            else if (action === 'codeBlock') active = editor.isActive('codeBlock');
            else if (action === 'blockquote') active = editor.isActive('blockquote');
            else if (action === 'bulletList') active = editor.isActive('bulletList');
            else if (action === 'orderedList') active = editor.isActive('orderedList');
            else if (action === 'callout') active = editor.isActive('callout');
            else if (action === 'alignLeft') active = editor.isActive({ textAlign: 'left' });
            else if (action === 'alignCenter') active = editor.isActive({ textAlign: 'center' });
            else if (action === 'alignRight') active = editor.isActive({ textAlign: 'right' });
            btn.classList.toggle(ACTIVE_CLASSES[0], active);
            btn.classList.toggle(ACTIVE_CLASSES[1], active);
        });

        const formatSelect = toolbarEl.querySelector('[data-format-select]');
        if (formatSelect) {
            if (editor.isActive('heading', { level: 1 })) formatSelect.value = 'h1';
            else if (editor.isActive('heading', { level: 2 })) formatSelect.value = 'h2';
            else if (editor.isActive('heading', { level: 3 })) formatSelect.value = 'h3';
            else formatSelect.value = 'p';
        }
    }

    // Live outline — a running list of the document's headings, updated on
    // every edit, so the author can see the article's structure while
    // writing (not just after publishing, where article_detail.html builds
    // the reader-facing equivalent from the rendered HTML).
    function renderOutline() {
        if (!outlineEl) return;
        const headings = [];
        editor.state.doc.descendants((node, pos) => {
            if (node.type.name === 'heading') {
                headings.push({ level: node.attrs.level, text: node.textContent || '(empty heading)', pos });
            }
        });
        if (headings.length === 0) {
            outlineEl.innerHTML = '<p class="text-xs text-text-secondary italic">Headings you add will show up here.</p>';
            return;
        }
        outlineEl.innerHTML = headings.map((h) => (
            `<button type="button" data-outline-pos="${h.pos}" class="block w-full text-left text-xs py-1 truncate hover:text-primary text-text-secondary"` +
            ` style="padding-left:${(h.level - 1) * 0.75}rem">${h.text}</button>`
        )).join('');
        outlineEl.querySelectorAll('[data-outline-pos]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const pos = Number(btn.dataset.outlinePos);
                editor.commands.focus(pos);
                const domNode = editor.view.domAtPos(pos).node;
                const el = domNode.nodeType === 1 ? domNode : domNode.parentElement;
                el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
        });
    }

    // Contextual table controls — only shown while the cursor is inside a
    // table, since "add a row/column" only makes sense there. Answers "how
    // do I make the table bigger than what I inserted" without needing a
    // permanent toolbar section that's irrelevant most of the time.
    function renderTableControls() {
        if (!tableControlsEl) return;
        tableControlsEl.classList.toggle('hidden', !editor.isActive('table'));
    }

    toolbarEl.querySelectorAll('[data-action]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const action = actions[btn.dataset.action];
            if (action) action();
        });
    });

    if (tableControlsEl) {
        tableControlsEl.querySelectorAll('[data-action]').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const action = actions[btn.dataset.action];
                if (action) action();
            });
        });
    }

    const formatSelect = toolbarEl.querySelector('[data-format-select]');
    if (formatSelect) {
        formatSelect.addEventListener('change', () => {
            const value = formatSelect.value;
            if (value === 'p') editor.chain().focus().setParagraph().run();
            else editor.chain().focus().setHeading({ level: Number(value.slice(1)) }).run();
        });
    }

    renderToolbarState();
    renderTableControls();
    renderOutline();
    return editor;
}
