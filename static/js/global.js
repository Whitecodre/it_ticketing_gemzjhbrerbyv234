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
        // Sidebar is visible - show X icon
        sidebar.classList.remove('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
        sidebar.classList.add('w-64');
        mainContent.classList.remove('md:ml-0');
        mainContent.classList.add('md:ml-64');
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
        }
    } else {
        // Sidebar is hidden - show menu icon
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
// SIDEBAR ACCORDION - Single Open, Default Closed (FIXED)
// ================================================================

let activeSectionId = null;

function closeAllSections(exceptSectionId = null) {
    const toggleBtns = document.querySelectorAll('.sidebar-section-toggle[data-section]');
    toggleBtns.forEach(function(button) {
        const sectionId = button.dataset.section;
        if (sectionId === exceptSectionId) return;
        if (!sectionId) return;
        
        const content = document.getElementById(sectionId);
        if (!content) return;
        
        content.style.maxHeight = '0px';
        content.style.opacity = '0';
        content.style.overflow = 'hidden';
        
        if (content._sidebarCloseTimer) {
            clearTimeout(content._sidebarCloseTimer);
        }

        content._sidebarCloseTimer = setTimeout(function() {
            content.classList.add('hidden');
            content._sidebarCloseTimer = null;
        }, 300);
        
        const chevron = button.querySelector('.section-chevron');
        if (chevron) chevron.style.transform = 'rotate(-90deg)';
        button.setAttribute('aria-expanded', 'false');
    });
}

function openSection(sectionId) {
    const content = document.getElementById(sectionId);
    if (!content) return;
    
    const button = document.querySelector(`.sidebar-section-toggle[data-section="${sectionId}"]`);
    if (!button) return;

    // A section can be reopened before its close animation has finished.
    // Cancel that pending hide so it remains visible.
    if (content._sidebarCloseTimer) {
        clearTimeout(content._sidebarCloseTimer);
        content._sidebarCloseTimer = null;
    }
    
    content.classList.remove('hidden');
    content.style.maxHeight = '0px';
    content.style.opacity = '0';
    content.style.overflow = 'hidden';
    
    // Force reflow
    void content.offsetHeight;
    
    const fullHeight = content.scrollHeight + 'px';
    content.style.maxHeight = fullHeight;
    content.style.opacity = '1';
    content.style.overflow = '';
    
    const chevron = button.querySelector('.section-chevron');
    if (chevron) chevron.style.transform = 'rotate(0deg)';
    button.setAttribute('aria-expanded', 'true');
}

function handleSectionToggle(e) {
    // Stop event from bubbling up
    e.stopPropagation();
    e.preventDefault();
    
    const button = e.currentTarget;
    const sectionId = button.getAttribute('data-section');
    if (!sectionId) return;
    
    const content = document.getElementById(sectionId);
    if (!content) return;
    
    const isCurrentlyOpen = activeSectionId === sectionId;
    
    // If clicking the already open section, close it
    if (isCurrentlyOpen) {
        closeAllSections();
        activeSectionId = null;
        return;
    }
    
    // Close all, then open this one
    closeAllSections(sectionId);
    openSection(sectionId);
    activeSectionId = sectionId;
}

// Sidebar links mark themselves active with an inline
// "background-color: var(--color-primary)" style rendered server-side (see
// templates/partials/sidebar_*.html). Reading that back client-side lets us
// find which section the current page lives in without duplicating each
// template's own active-link conditions.
function findActiveSectionId(sectionIds) {
    for (const sectionId of sectionIds) {
        const content = document.getElementById(sectionId);
        if (!content) continue;
        if (content.querySelector('.sidebar-link[style*="background-color"]')) {
            return sectionId;
        }
    }
    return null;
}

function initialiseSidebarAccordion() {
    const toggleBtns = document.querySelectorAll('.sidebar-section-toggle[data-section]');

    if (!toggleBtns || toggleBtns.length === 0) {
        setTimeout(initialiseSidebarAccordion, 100);
        return;
    }

    // Remove existing click listeners by cloning and replacing
    toggleBtns.forEach(function(button) {
        // Store the section id before cloning
        const sectionId = button.dataset.section;
        // Clone the button
        const newButton = button.cloneNode(true);
        // Replace the original with the clone
        button.parentNode.replaceChild(newButton, button);
    });

    // Get fresh references after replacement
    const freshBtns = document.querySelectorAll('.sidebar-section-toggle[data-section]');
    const sectionIds = Array.prototype.map.call(freshBtns, function (b) { return b.dataset.section; }).filter(Boolean);

    // Open whichever section contains the current page's active link, so a
    // visitor lands with their location already visible instead of landing
    // on an all-collapsed sidebar and having to guess which group to open.
    const sectionToOpen = findActiveSectionId(sectionIds);

    // Mark the parent category with the same "you are here" signal the
    // child link gets, so collapsing the section (to browse elsewhere)
    // doesn't lose the visual trail back to the current page.
    freshBtns.forEach(function(button) {
        button.classList.toggle('has-active-child', button.dataset.section === sectionToOpen);
    });

    // Start all closed, except the section we're about to open below.
    freshBtns.forEach(function(button) {
        const sectionId = button.dataset.section;
        if (!sectionId || sectionId === sectionToOpen) return;

        const content = document.getElementById(sectionId);
        if (!content) return;

        content.classList.add('hidden');
        content.style.maxHeight = '0px';
        content.style.opacity = '0';
        content.style.overflow = 'hidden';

        const chevron = button.querySelector('.section-chevron');
        if (chevron) chevron.style.transform = 'rotate(-90deg)';
        button.setAttribute('aria-expanded', 'false');
    });

    activeSectionId = null;

    // Add fresh event listeners
    freshBtns.forEach(function(button) {
        button.addEventListener('click', handleSectionToggle);
    });

    if (sectionToOpen) {
        openSection(sectionToOpen);
        activeSectionId = sectionToOpen;
    }
}

// Re-initialize after HTMX swaps that replace the sidebar nav itself (e.g.
// a role switch). Deliberately NOT matching `.closest('#sidebarNav')` here —
// small polling widgets nested inside the nav (like the remote-session
// count badge, which refreshes on its own "every 5s" trigger) also bubble
// htmx:afterSwap, and a full re-init collapses whatever section the user
// had manually opened back to just the active one every time they fire.
document.addEventListener('htmx:afterSwap', function(event) {
    if (event.target.id === 'sidebarNav' || event.target.id === 'sidebar') {
        // Reset and re-initialize after a small delay
        setTimeout(function() {
            initialiseSidebarAccordion();
        }, 100);
    }
});

// Handle Dashboard link
document.addEventListener('DOMContentLoaded', function() {
    const dashboardLink = document.getElementById('dashboardLink');
    if (dashboardLink) {
        dashboardLink.addEventListener('click', function() {
            closeAllSections();
            activeSectionId = null;
        });
    }
});

// ================================================================
// NOTIFICATIONS DROPDOWN - FIXED
// ================================================================

function toggleNotificationDropdown() {
    const dropdown = document.getElementById('notificationDropdown');
    const bell = document.getElementById('notificationBell');
    if (!dropdown) return;
    if (dropdown.classList.contains('hidden')) {
        if (window.htmx && bell) {
            // Load notifications
            const url = window.notificationsUrl || '/notifications/list/';
            htmx.ajax('GET', url, {
                target: '#notificationDropdownContent',
                swap: 'innerHTML'
            });
        }
    }
    dropdown.classList.toggle('hidden');
}

// ================================================================
// NOTIFICATIONS - Mark Read and Go
// ================================================================

function markReadAndGo(url, notificationId) {
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    fetch('/notifications/mark-read/' + notificationId + '/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken || ''
        }
    }).then(() => {
        if (!window.htmx) return;
        htmx.ajax('GET', '/notifications/unread-count/', {
            target: '#notificationBadgeContainer',
            swap: 'innerHTML'
        });
        htmx.ajax('GET', '/notifications/list/', {
            target: '#notificationDropdownContent',
            swap: 'innerHTML'
        });
    });
    if (url) {
        window.location.href = url;
    }
}

// Close notification dropdown on outside click
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
        panel.style.display = 'block';
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
// FULFILLMENT MODAL (asset fulfillment for pending-fulfillment tickets)
// ================================================================

function openFulfillModal(ticketId) {
    // Remove any existing modal
    const existing = document.getElementById('fulfillModal');
    if (existing) existing.remove();

    // Disable body scroll
    document.body.style.overflow = 'hidden';

    // Fetch the modal content
    fetch(`/tickets/assets/fulfill-modal/${ticketId}/`)
        .then(response => response.text())
        .then(html => {
            const wrapper = document.createElement('div');
            wrapper.innerHTML = html;
            document.body.appendChild(wrapper.firstElementChild);

            // Re-initialize HTMX for dynamically loaded content
            const modal = document.getElementById('fulfillModal');
            if (modal && typeof htmx !== 'undefined') {
                htmx.process(modal);
            }

            // Click on backdrop closes modal
            if (modal) {
                modal.addEventListener('click', function(e) {
                    if (e.target === this || e.target.hasAttribute('data-modal-backdrop')) {
                        closeFulfillModal();
                    }
                });
            }
        })
        .catch(error => {
            console.error('Error loading fulfill modal:', error);
            document.body.style.overflow = '';
            if (typeof showToast === 'function') {
                showToast('Error loading fulfillment form.', 'error');
            }
        });
}

function closeFulfillModal() {
    const modal = document.getElementById('fulfillModal');
    if (modal) {
        modal.remove();
    }
    document.body.style.overflow = '';
}

window.openFulfillModal = openFulfillModal;
window.closeFulfillModal = closeFulfillModal;

// Close on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeFulfillModal();
    }
});

// Handle data-close-modal buttons using event delegation
document.addEventListener('click', function(e) {
    const closeBtn = e.target.closest('[data-close-modal]');
    if (closeBtn) {
        e.preventDefault();
        closeFulfillModal();
    }
});

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
// DOUBLE-SUBMIT PROTECTION
// ================================================================
// Disables the submit button on a form's first submit, so a rapid
// double-click/double-Enter can't fire the request twice.
function preventDoubleSubmit(form) {
    if (!form || form.dataset.doubleSubmitGuarded === 'true') return;
    form.dataset.doubleSubmitGuarded = 'true';
    form.addEventListener('submit', function() {
        const btn = form.querySelector('button[type="submit"]');
        if (btn && !btn.disabled) {
            btn.disabled = true;
            btn.classList.add('opacity-70');
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('form[data-guard-submit]').forEach(preventDoubleSubmit);
});

// ================================================================
// THEME TOGGLE
// ================================================================

function setTheme(theme) {
    const isDark = theme === 'dark';
    document.documentElement.classList.toggle('dark', isDark);
    localStorage.setItem('theme', theme);
    
    // Update radio buttons
    document.querySelectorAll('.theme-radio[data-theme]').forEach(function(label) {
        const isActive = label.dataset.theme === theme;
        label.classList.toggle('active', isActive);
        const radio = label.querySelector('input[type="radio"]');
        if (radio) radio.checked = isActive;
    });
}

// ================================================================
// ROLE DROPDOWN
// ================================================================

function toggleRoleDropdown() {
    const dropdown = document.getElementById('roleDropdown');
    if (dropdown) {
        dropdown.classList.toggle('hidden');
    }
}

// Close role dropdown on outside click
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('roleDropdown');
    if (dropdown && !dropdown.classList.contains('hidden')) {
        const button = event.target.closest('[onclick="toggleRoleDropdown()"]');
        if (!button && !dropdown.contains(event.target)) {
            dropdown.classList.add('hidden');
        }
    }
});

// ================================================================
// TOAST NOTIFICATIONS
// ================================================================

function showToast(message, type = 'info', duration = 5000) {
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
    toast.className = `toast-item toast-fallback toast-${typeClass}`;
    
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
