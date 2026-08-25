// global.js – Global utility functions (NO ALPINE.JS COMPONENTS)

// ================================================================
// SHARED DROPDOWN POSITIONING
// ================================================================
// Positions a dropdown panel with `position: fixed`, anchored to its
// trigger element, flipping/aligning to stay inside the viewport, and
// re-computing on resize/scroll while open. This is the one place the
// flip/clamp math lives — used by the notification bell, role switcher,
// status menu, macro menu, export menus, and the per-row table action
// menus, replacing several copy-pasted versions of the same logic.
//
// options:
//   align: 'right' (default) | 'left' | 'center' — horizontal anchor
//          relative to the trigger element's own edges/center
//   direction: 'auto' (default) | 'down' | 'up' — vertical placement;
//          'auto' opens downward unless there isn't room below and
//          there's more room above than below
//   margin: viewport-edge clamp margin in px (default 8)
//   gap: gap between trigger and dropdown in px (default 6)
//
// Returns a cleanup() function that removes the resize/scroll listeners
// this call attached — call it when the dropdown closes so listeners
// don't leak.
function positionDropdown(triggerEl, dropdownEl, options) {
    options = options || {};
    const margin = options.margin != null ? options.margin : 8;
    const gap = options.gap != null ? options.gap : 6;
    const align = options.align || 'right';
    const direction = options.direction || 'auto';

    function measure() {
        // A `hidden` (display:none) element reports zero size. If that's
        // the state we're in, measure it invisibly-but-rendered first.
        const wasHidden = dropdownEl.classList.contains('hidden');
        let prevVisibility, prevDisplay;
        if (wasHidden) {
            prevVisibility = dropdownEl.style.visibility;
            prevDisplay = dropdownEl.style.display;
            dropdownEl.classList.remove('hidden');
            dropdownEl.style.visibility = 'hidden';
            dropdownEl.style.display = 'block';
        }

        const width = dropdownEl.offsetWidth;
        const height = dropdownEl.offsetHeight;

        if (wasHidden) {
            dropdownEl.classList.add('hidden');
            dropdownEl.style.visibility = prevVisibility;
            dropdownEl.style.display = prevDisplay;
        }
        return { width, height };
    }

    function compute() {
        if (!triggerEl || !dropdownEl) return;
        const triggerRect = triggerEl.getBoundingClientRect();
        const { width, height } = measure();

        const spaceBelow = window.innerHeight - triggerRect.bottom - gap - margin;
        const spaceAbove = triggerRect.top - gap - margin;
        let openUp;
        if (direction === 'up') openUp = true;
        else if (direction === 'down') openUp = false;
        else openUp = height > spaceBelow && spaceAbove > spaceBelow;

        let top = openUp ? triggerRect.top - height - gap : triggerRect.bottom + gap;
        const maxTop = window.innerHeight - height - margin;
        top = Math.max(margin, Math.min(top, maxTop));

        let left;
        if (align === 'left') left = triggerRect.left;
        else if (align === 'center') left = triggerRect.left + triggerRect.width / 2 - width / 2;
        else left = triggerRect.right - width;
        const maxLeft = window.innerWidth - width - margin;
        left = Math.max(margin, Math.min(left, maxLeft));

        dropdownEl.style.position = 'fixed';
        dropdownEl.style.top = top + 'px';
        dropdownEl.style.left = left + 'px';
        dropdownEl.style.right = 'auto';
        dropdownEl.style.bottom = 'auto';
    }

    compute();
    window.addEventListener('resize', compute);
    // scroll doesn't bubble, so listen in the capture phase to catch
    // scrolling on any ancestor container, not just window/document.
    window.addEventListener('scroll', compute, true);

    return function cleanupPositionDropdown() {
        window.removeEventListener('resize', compute);
        window.removeEventListener('scroll', compute, true);
    };
}
window.positionDropdown = positionDropdown;

// ================================================================
// SHARED ACTION DROPDOWN — one instance per table, opened/closed/
// repositioned per row via a single trigger button, so every "kebab"
// Actions-column dropdown (asset inventory, ticket tables, user table,
// ...) shares the exact same toggle-to-close and positioning behavior
// instead of each table hand-rolling a slightly different copy.
//
// Usage: call once per dropdown element to get back { toggle, close,
// isOpen }, then have each row's trigger button call toggle(btn) —
// toggle() closes the dropdown if it's already open for that same
// button (true toggle behavior), otherwise repositions/opens it for
// the new button via positionDropdown(). onOpen(btn) runs right before
// opening — populate the dropdown's content (labels, hrefs, per-row
// data) from btn.dataset there.
//
// options:
//   align: passed straight through to positionDropdown (default 'right')
//   onOpen(btn): called before the dropdown opens for a given trigger
//   onClose(): called whenever the dropdown closes, for any reason
// ================================================================
function createActionDropdown(dropdownEl, options) {
    options = options || {};
    const align = options.align || 'right';
    let activeBtn = null;
    let cleanup = null;

    function isOpen() {
        return dropdownEl.classList.contains('opacity-100');
    }

    function close() {
        dropdownEl.classList.remove('opacity-100', 'scale-100');
        dropdownEl.classList.add('pointer-events-none', 'opacity-0', 'scale-95');
        activeBtn = null;
        if (cleanup) { cleanup(); cleanup = null; }
        if (options.onClose) options.onClose();
    }

    function toggle(btn) {
        const reopening = activeBtn === btn && isOpen();
        close();
        if (reopening) return false;
        activeBtn = btn;
        if (options.onOpen) options.onOpen(btn);
        if (window.positionDropdown) {
            cleanup = window.positionDropdown(btn, dropdownEl, { align: align });
        }
        dropdownEl.classList.remove('pointer-events-none', 'opacity-0', 'scale-95');
        dropdownEl.classList.add('opacity-100', 'scale-100');
        return true;
    }

    // Identity-based, not selector-based: activeBtn is already updated
    // by toggle() before this bubbles up here (inline onclick and
    // document-delegated trigger handlers both run before/at this
    // point), so this works regardless of the trigger's class name or
    // how its click handler is wired.
    document.addEventListener('click', function(e) {
        if (activeBtn && (e.target === activeBtn || activeBtn.contains(e.target))) return;
        if (!dropdownEl.contains(e.target)) close();
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') close();
    });

    return { toggle: toggle, close: close, isOpen: isOpen };
}
window.createActionDropdown = createActionDropdown;

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
        sidebar.classList.add('sidebar-mobile-open');
        backdrop.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        if (toggleIcon) {
            toggleIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
        }
    } else {
        sidebar.classList.remove('sidebar-mobile-open');
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
            sidebar.classList.remove('sidebar-mobile-open');
            backdrop.classList.add('hidden');
            document.body.style.overflow = '';
            mobileSidebarOpen = false;
            updateDesktopSidebar();
        } else {
            const sidebar = document.getElementById('sidebar');
            const backdrop = document.getElementById('sidebarBackdrop');
            sidebar.classList.remove('sidebar-mobile-open');
            backdrop.classList.add('hidden');
            document.body.style.overflow = '';
            mobileSidebarOpen = false;
            sidebar.classList.remove('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
            sidebar.classList.add('w-64');
        }
    }, 200);
});

// ================================================================
// SIDEBAR - Apply correct initial state on page load
// ================================================================
// The `resize` listener above only runs on an actual resize of an
// already-loaded page - it never fires for a fresh page load that starts
// at a small (mobile) viewport, or one where the desktop "sidebar hidden"
// preference was saved to localStorage. Without this, every fresh mobile
// page load renders the full desktop sidebar on top of the content, and
// the desktop collapsed-sidebar preference is never honoured on load.
(function initSidebarState() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (!sidebar) return;

    if (window.innerWidth < 768) {
        sidebar.classList.remove('sidebar-mobile-open');
        if (backdrop) backdrop.classList.add('hidden');
        sidebar.classList.remove('w-0', 'overflow-hidden', 'border-r-0', 'px-0');
        sidebar.classList.add('w-64');
    } else {
        sidebar.classList.remove('sidebar-mobile-open');
        updateDesktopSidebar();
    }
})();

// ================================================================
// SIDEBAR ACCORDION - Single Open, Closed By Default Except Active
// ================================================================

let activeSectionId = null;

function closeAllSections(exceptSectionId = null, instant = false) {
    const toggleBtns = document.querySelectorAll('.sidebar-section-toggle[data-section]');
    toggleBtns.forEach(function(button) {
        const sectionId = button.dataset.section;
        if (sectionId === exceptSectionId) return;
        if (!sectionId) return;

        const content = document.getElementById(sectionId);
        if (!content) return;

        if (instant) {
            // Skip the animation entirely on first paint so a fresh page
            // load doesn't flash every section open before collapsing them.
            content.style.transition = 'none';
            content.style.maxHeight = '0px';
            content.style.opacity = '0';
            content.style.overflow = 'hidden';
            content.classList.add('hidden');
            void content.offsetHeight;
            content.style.transition = '';
        } else {
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
        }

        const chevron = button.querySelector('.section-chevron');
        if (chevron) chevron.style.transform = 'rotate(-90deg)';
        button.setAttribute('aria-expanded', 'false');
        updateParentBadgeVisibility(button);
    });
}

function openSection(sectionId, instant = false) {
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

    if (instant) content.style.transition = 'none';

    content.style.maxHeight = '0px';
    content.style.opacity = '0';
    content.style.overflow = 'hidden';

    // Force reflow
    void content.offsetHeight;

    const fullHeight = content.scrollHeight + 'px';
    content.style.maxHeight = fullHeight;
    content.style.opacity = '1';
    content.style.overflow = '';

    if (instant) {
        void content.offsetHeight;
        content.style.transition = '';
    }

    const chevron = button.querySelector('.section-chevron');
    if (chevron) chevron.style.transform = 'rotate(0deg)';
    button.setAttribute('aria-expanded', 'true');
    updateParentBadgeVisibility(button);
}

// ================================================================
// SIDEBAR BADGE PROPAGATION
// ================================================================
// Sums the pending-count badges (.badge-pending, excluding the parent
// badge itself) inside a collapsed section and shows the total on that
// section's header, so a user browsing elsewhere still sees "something
// here needs attention" without expanding the group. Hidden again while
// the section is open — the child badges are visible directly then,
// which reads cleaner than showing the same count twice.
function getOrCreateSectionBadge(button) {
    let badge = button.querySelector('.sidebar-section-badge');
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'sidebar-section-badge badge-pending hidden';
        const chevron = button.querySelector('.section-chevron');
        if (chevron) {
            button.insertBefore(badge, chevron);
        } else {
            button.appendChild(badge);
        }
    }
    return badge;
}

function sumSectionBadgeCount(content) {
    let total = 0;
    content.querySelectorAll('.badge-pending').forEach(function(el) {
        if (el.classList.contains('sidebar-section-badge')) return;
        const n = parseInt((el.textContent || '').trim(), 10);
        if (!isNaN(n)) total += n;
    });
    return total;
}

function updateParentBadgeVisibility(button) {
    const sectionId = button.dataset.section;
    if (!sectionId) return;
    const content = document.getElementById(sectionId);
    if (!content) return;

    const total = sumSectionBadgeCount(content);
    const badge = getOrCreateSectionBadge(button);
    const isExpanded = button.getAttribute('aria-expanded') === 'true';

    if (total > 0 && !isExpanded) {
        badge.textContent = total > 99 ? '99+' : String(total);
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function refreshSidebarBadges() {
    document.querySelectorAll('.sidebar-section-toggle[data-section]').forEach(function(button) {
        updateParentBadgeVisibility(button);
    });
}

// Child badges (Remote Sessions, My Assets, Manager Review, ...) refresh
// on their own independent HTMX polling intervals — recompute the
// relevant parent's aggregate whenever any of them swaps in new content.
document.addEventListener('htmx:afterSwap', function(event) {
    if (event.target.closest && event.target.closest('.section-content')) {
        refreshSidebarBadges();
    }
});

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

    // Mark the section containing the current page's active link with the
    // same "you are here" signal the child link gets.
    const sectionToOpen = findActiveSectionId(sectionIds);
    freshBtns.forEach(function(button) {
        button.classList.toggle('has-active-child', button.dataset.section === sectionToOpen);
    });

    // Every section starts closed except the one containing the current
    // page, so the user can see where they are without hunting for it.
    // `instant: true` skips the open/close animation on this first pass so
    // a fresh page load doesn't flash every section open before collapsing
    // them. Clicking a section afterward still closes the others (see
    // handleSectionToggle) - only the initial state changed.
    closeAllSections(sectionToOpen, true);
    if (sectionToOpen) {
        openSection(sectionToOpen, true);
    }
    activeSectionId = sectionToOpen;

    // Add fresh event listeners
    freshBtns.forEach(function(button) {
        button.addEventListener('click', handleSectionToggle);
    });

    refreshSidebarBadges();
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

let notificationDropdownCleanup = null;

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
        dropdown.classList.remove('hidden');
        if (bell) {
            notificationDropdownCleanup = positionDropdown(bell, dropdown, { align: 'right' });
        }
    } else {
        dropdown.classList.add('hidden');
        if (notificationDropdownCleanup) {
            notificationDropdownCleanup();
            notificationDropdownCleanup = null;
        }
    }
}

// positionDropdown() above measures the dropdown synchronously right when
// it opens, but the real notification list loads asynchronously via HTMX
// afterward — on the first open per page (before anything's cached in the
// DOM), that measurement happens against the short "Loading notifications…"
// placeholder, so the box gets positioned/sized for that instead of the
// real (usually much taller) list. Recompute once the swap actually lands.
document.body.addEventListener('htmx:afterSwap', function(event) {
    if (event.detail.target && event.detail.target.id === 'notificationDropdownContent') {
        const dropdown = document.getElementById('notificationDropdown');
        const bell = document.getElementById('notificationBell');
        if (dropdown && bell && !dropdown.classList.contains('hidden')) {
            if (notificationDropdownCleanup) notificationDropdownCleanup();
            notificationDropdownCleanup = positionDropdown(bell, dropdown, { align: 'right' });
        }
    }
});

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
        if (notificationDropdownCleanup) {
            notificationDropdownCleanup();
            notificationDropdownCleanup = null;
        }
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

// ================================================================
// VENDOR-BY-CATEGORY FILTER
// Narrows an already-rendered vendor <select> to vendors that supply the
// category picked in a sibling <select> — options are pre-tagged with
// data-categories="1,3" (comma-separated AssetCategory pks) by the server;
// a vendor with no data-categories (uncategorized) always stays visible.
// Used by the "Order from Vendor" procurement form, each mobilization
// procurement line item, and the asset renewal-vendor picker.
// ================================================================

function filterVendorSelectByCategory(categorySelect, vendorSelect) {
    if (!categorySelect || !vendorSelect) return;
    const categoryId = categorySelect.value;
    const previousValue = vendorSelect.value;
    let stillValid = !categoryId;

    Array.from(vendorSelect.options).forEach(function (opt) {
        if (!opt.value) { opt.hidden = false; return; }
        const raw = opt.dataset.categories || '';
        const cats = raw ? raw.split(',') : [];
        const matches = !categoryId || cats.length === 0 || cats.indexOf(categoryId) !== -1;
        opt.hidden = !matches;
        if (matches && opt.value === previousValue) stillValid = true;
    });

    if (!stillValid) vendorSelect.value = '';
}

window.filterVendorSelectByCategory = filterVendorSelectByCategory;

// ================================================================
// MOBILIZE ASSETS — navigates to its own page (tickets/mobilization_create.html)
// rather than opening in the slideover. The form is too long/multi-section
// for a slideover to do well; every call site still calls this same
// function name with the same (optional) ticketId argument, so nothing
// else had to change at the call sites themselves.
// ================================================================

function openMobilizationCreateModal(ticketId) {
    window.location.href = ticketId
        ? `/tickets/mobilizations/new/?ticket_id=${ticketId}`
        : '/tickets/mobilizations/new/';
}

window.openMobilizeModal = openMobilizationCreateModal;
window.openMobilizationCreateModal = openMobilizationCreateModal;
window.closeMobilizationModal = closeSlideover;

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeMobilizationModal();
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
// HTMX ERROR RESPONSES -> TOAST
// ================================================================
// HTMX doesn't swap non-2xx responses by default, so a failed hx-post
// (e.g. an empty comment, a rejected form) otherwise looks like nothing
// happened at all. Fall back to a toast wherever nothing more specific
// already handles htmx:responseError on a given element.
document.body.addEventListener('htmx:responseError', function(event) {
    if (typeof showToast !== 'function') return;
    const xhr = event.detail.xhr;
    const raw = (xhr && xhr.responseText || '').trim();
    // Plain-text error bodies (the common case) are shown as-is; a few
    // older endpoints still return an HTML fragment with a 4xx status
    // (meant to be swapped in, back when this had no fallback) — showing
    // those tags-and-all in a toast would look broken, so fall back to a
    // generic message for anything that looks like markup instead.
    const message = raw && !raw.startsWith('<') ? raw : 'Something went wrong. Please try again.';
    showToast(message, 'error');
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

let roleDropdownCleanup = null;

function toggleRoleDropdown() {
    const dropdown = document.getElementById('roleDropdown');
    if (!dropdown) return;
    if (dropdown.classList.contains('hidden')) {
        dropdown.classList.remove('hidden');
        const trigger = document.querySelector('[onclick="toggleRoleDropdown()"]');
        if (trigger) {
            roleDropdownCleanup = positionDropdown(trigger, dropdown, { align: 'right' });
        }
    } else {
        dropdown.classList.add('hidden');
        if (roleDropdownCleanup) {
            roleDropdownCleanup();
            roleDropdownCleanup = null;
        }
    }
}

// Close role dropdown on outside click
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('roleDropdown');
    if (dropdown && !dropdown.classList.contains('hidden')) {
        const button = event.target.closest('[onclick="toggleRoleDropdown()"]');
        if (!button && !dropdown.contains(event.target)) {
            dropdown.classList.add('hidden');
            if (roleDropdownCleanup) {
                roleDropdownCleanup();
                roleDropdownCleanup = null;
            }
        }
    }
});

// ================================================================
// TOAST NOTIFICATIONS
// ================================================================

// Errors tend to carry longer, more important text than a short "Saved"
// confirmation — give them more time on screen by default instead of the
// same fixed window for every toast type. Callers that pass an explicit
// duration still get exactly that.
const TOAST_DEFAULT_DURATION_BY_TYPE = { error: 8000, warning: 7000, success: 4000, info: 5000 };

function showToast(message, type = 'info', duration) {
    if (duration === undefined) duration = TOAST_DEFAULT_DURATION_BY_TYPE[type] || 5000;
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
