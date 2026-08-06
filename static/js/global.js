// global.js – Global utility functions (NO ALPINE.JS COMPONENTS)

// ================================================================
// SIDEBAR STATE - Initialize
// ================================================================

let mobileSidebarOpen = false;
let desktopSidebarVisible = localStorage.getItem('sidebar_visible') !== 'false';

// ================================================================
// SIDEBAR TOGGLE (Mobile/Desktop)
// ================================================================

function toggleSidebarMain() {
    const isMobile = window.innerWidth < 768;
    if (isMobile) {
        mobileSidebarOpen = !mobileSidebarOpen;
        updateMobileSidebar();
    } else {
        desktopSidebarVisible = !desktopSidebarVisible;
        localStorage.setItem('sidebar_visible', desktopSidebarVisible);
        updateDesktopSidebar();
    }
}

function updateMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    const toggleIcon = document.getElementById('toggleIcon');
    
    if (mobileSidebarOpen) {
        sidebar.classList.remove('-translate-x-full');
        backdrop.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
        }
    } else {
        sidebar.classList.add('-translate-x-full');
        backdrop.classList.add('hidden');
        document.body.style.overflow = '';
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>`;
        }
    }
}

function updateDesktopSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    const toggleIcon = document.getElementById('toggleIcon');
    
    if (desktopSidebarVisible) {
        sidebar.classList.remove('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
        sidebar.classList.add('w-64');
        mainContent.classList.remove('md:ml-0');
        mainContent.classList.add('md:ml-64');
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>`;
        }
    } else {
        sidebar.classList.remove('w-64');
        sidebar.classList.add('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
        mainContent.classList.remove('md:ml-64');
        mainContent.classList.add('md:ml-0');
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>`;
        }
    }
}

function closeSidebar() {
    if (window.innerWidth < 768) {
        mobileSidebarOpen = false;
        updateMobileSidebar();
    }
}

// Handle window resize
let resizeTimeout;
window.addEventListener('resize', function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function() {
        const isMobile = window.innerWidth < 768;
        if (window.innerWidth >= 768) {
            const sidebar = document.getElementById('sidebar');
            const backdrop = document.getElementById('sidebarBackdrop');
            sidebar.classList.remove('-translate-x-full');
            backdrop.classList.add('hidden');
            document.body.style.overflow = '';
            mobileSidebarOpen = false;
            updateDesktopSidebar();
        } else {
            const sidebar = document.getElementById('sidebar');
            const backdrop = document.getElementById('sidebarBackdrop');
            sidebar.classList.add('-translate-x-full');
            backdrop.classList.add('hidden');
            document.body.style.overflow = '';
            mobileSidebarOpen = false;
            sidebar.classList.remove('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
            sidebar.classList.add('w-64');
        }
    }, 200);
});

// ================================================================
// NOTIFICATIONS DROPDOWN
// ================================================================

function toggleNotificationDropdown() {
    const dropdown = document.getElementById('notificationDropdown');
    const bell = document.getElementById('notificationBell');
    if (dropdown.classList.contains('hidden')) {
        htmx.trigger('#notificationBell', 'load-notifications');
    }
    dropdown.classList.toggle('hidden');
}

document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('notificationDropdown');
    const bell = document.getElementById('notificationBell');
    if (dropdown && bell && !bell.contains(event.target) && !dropdown.contains(event.target)) {
        dropdown.classList.add('hidden');
    }
});

// ================================================================
// SLIDEOVER FUNCTIONS
// ================================================================

function openSlideover() {
    const panel = document.getElementById('ticketSlideover');
    const backdrop = document.getElementById('slideoverBackdrop');
    if (panel) {
        panel.classList.remove('translate-x-full');
        panel.classList.add('translate-x-0');
        panel.style.transform = 'translateX(0)';
    }
    if (backdrop) {
        backdrop.classList.remove('hidden');
        backdrop.style.display = 'block';
    }
    document.body.style.overflow = 'hidden';
}

function closeSlideover() {
    const panel = document.getElementById('ticketSlideover');
    const backdrop = document.getElementById('slideoverBackdrop');
    if (panel) {
        panel.classList.add('translate-x-full');
        panel.classList.remove('translate-x-0');
        panel.style.transform = 'translateX(100%)';
    }
    if (backdrop) {
        backdrop.classList.add('hidden');
        backdrop.style.display = 'none';
    }
    document.body.style.overflow = '';
    setTimeout(() => {
        const content = document.getElementById('slideoverContent');
        if (content) content.innerHTML = '';
    }, 300);
}

window.openSlideover = openSlideover;
window.closeSlideover = closeSlideover;

// ================================================================
// CSRF TOKEN FOR HTMX
// ================================================================

document.body.addEventListener('htmx:configRequest', function(event) {
    const tokenElem = document.querySelector('[name=csrfmiddlewaretoken]');
    if (tokenElem) {
        event.detail.headers['X-CSRFToken'] = tokenElem.value;
    }
});

// ================================================================
// MARK NOTIFICATION AS READ
// ================================================================

function markReadAndGo(url, notificationId) {
    fetch('/notifications/mark-read/' + notificationId + '/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
    }).then(() => {
        htmx.ajax('GET', '/notifications/unread-count/', {target:'#notificationBadgeContainer', swap:'innerHTML'});
        htmx.ajax('GET', '/notifications/list/', {target:'#notificationDropdownContent', swap:'innerHTML'});
    });
    if (url) {
        window.location.href = url;
    }
}

// ================================================================
// RICH TEXT EDITOR
// ================================================================

let currentEditableDiv = null;

function initRichTextEditor(divId, hiddenInputId) {
    const editor = document.getElementById(divId);
    const hidden = document.getElementById(hiddenInputId);
    if (!editor || !hidden) return;
    currentEditableDiv = editor;

    const form = editor.closest('form');
    if (form) {
        form.addEventListener('submit', function() {
            hidden.value = editor.innerHTML;
        });
    }

    const draftKey = editor.getAttribute('data-draft-key');
    if (draftKey) {
        const saved = localStorage.getItem(draftKey);
        if (saved) editor.innerHTML = saved;
        editor.addEventListener('input', function() {
            localStorage.setItem(draftKey, editor.innerHTML);
        });
        form.addEventListener('htmx:afterRequest', function() {
            localStorage.removeItem(draftKey);
            editor.innerHTML = '';
        });
    }
}

function formatDocument(command, value = null) {
    if (!currentEditableDiv) return;
    currentEditableDiv.focus();
    document.execCommand(command, false, value);
}

// ================================================================
// TOAST NOTIFICATIONS - DELEGATES TO ALPINE.JS
// ================================================================

function showToast(message, type = 'info', duration = 5000) {
    // Try to find the Alpine.js toast manager
    const toastContainer = document.querySelector('[x-data="toastManager"]');
    
    if (toastContainer && toastContainer.__x) {
        try {
            const data = Alpine.$data(toastContainer);
            if (data && typeof data.addToast === 'function') {
                data.addToast(message, type, duration);
                return;
            }
        } catch (e) {
            console.warn('Alpine.js toast manager not available:', e);
        }
    }
    
    // Fallback: console log and create a simple toast
    console.log(`[${type.toUpperCase()}] ${message}`);
    createFallbackToast(message, type, duration);
}

function createFallbackToast(message, type = 'info', duration = 5000) {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    const typeClass = type || 'info';
    toast.className = `toast-item toast-${typeClass}`;
    
    const icons = {
        success: '<svg class="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
        error: '<svg class="h-5 w-5 text-error" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
        warning: '<svg class="h-5 w-5 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
        info: '<svg class="h-5 w-5 text-info" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
    };
    
    toast.innerHTML = `
        <div class="toast-content">
            <div class="toast-icon">${icons[type] || icons.info}</div>
            <div class="toast-body">
                <div class="toast-title">${type.charAt(0).toUpperCase() + type.slice(1)}</div>
                <div class="toast-message">${message}</div>
            </div>
            <button class="toast-dismiss" onclick="this.closest('.toast-item').remove()">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
        </div>
        <div class="toast-progress">
            <div class="toast-progress-bar" style="width: 100%;"></div>
        </div>
    `;
    
    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    
    const startTime = Date.now();
    const progressBar = toast.querySelector('.toast-progress-bar');
    
    function updateProgress() {
        const elapsed = Date.now() - startTime;
        const remaining = Math.max(0, 1 - elapsed / duration);
        if (progressBar) {
            progressBar.style.width = (remaining * 100) + '%';
        }
        if (elapsed < duration) {
            requestAnimationFrame(updateProgress);
        }
    }
    requestAnimationFrame(updateProgress);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Process Django messages after page load
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        const messagesData = document.getElementById('django-messages-data');
        if (messagesData) {
            try {
                const messages = JSON.parse(messagesData.dataset.messages);
                if (messages && messages.length > 0) {
                    messages.forEach(function(msg) {
                        let type = 'info';
                        if (msg.tags && msg.tags.includes('success')) type = 'success';
                        else if (msg.tags && msg.tags.includes('error')) type = 'error';
                        else if (msg.tags && msg.tags.includes('warning')) type = 'warning';
                        showToast(msg.text, type, 5000);
                    });
                }
            } catch (e) {
                console.error('Failed to parse messages:', e);
            }
        }
    }, 500);
});

// ================================================================
// CONFIRMATION MODAL - Legacy support
// ================================================================

let confirmCallback = null;

function openConfirmationModal(message, title = 'Confirm Action', confirmText = 'Confirm', confirmClass = 'btn-danger', callback) {
    const modal = document.getElementById('confirmationModal');
    const titleEl = document.getElementById('confirmModalTitle');
    const msgEl = document.getElementById('confirmModalMessage');
    const btn = document.getElementById('confirmModalBtn');

    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;
    if (btn) {
        btn.textContent = confirmText;
        btn.className = confirmClass + ' text-sm px-4 py-2 rounded-lg';
        confirmCallback = callback;
        const newBtn = btn.cloneNode(true);
        btn.parentNode.replaceChild(newBtn, btn);
        newBtn.addEventListener('click', function(e) {
            if (typeof confirmCallback === 'function') {
                confirmCallback();
            }
            closeConfirmationModal();
        });
    }

    modal.classList.remove('hidden');
}

function closeConfirmationModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById('confirmationModal');
    modal.classList.add('hidden');
    confirmCallback = null;
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeConfirmationModal();
    }
});

// ================================================================
// SPINNER ON FORM SUBMIT
// ================================================================

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('form[method="post"]').forEach(function(form) {
        form.addEventListener('submit', function() {
            const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="inline-flex items-center"><svg class="animate-spin h-4 w-4 mr-2 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Sending...</span>';
                submitBtn.classList.add('opacity-70');
            }
        });
    });
});