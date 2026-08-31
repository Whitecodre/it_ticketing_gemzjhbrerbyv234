// static/js/confirmation-modal.js
// ================================================================
// REUSABLE CONFIRMATION MODAL SYSTEM
// ================================================================

// Store the current confirmation callback
let confirmationCallback = null;
let confirmationContext = null;

/**
 * Open the confirmation modal with custom configuration
 * 
 * @param {Object} config - Configuration object
 * @param {string} config.title - Modal title
 * @param {string} config.message - Main message
 * @param {string} config.detail - Additional detail text (optional)
 * @param {string} config.confirmText - Text for confirm button (default: "Yes, I'm sure")
 * @param {string} config.cancelText - Text for cancel button (default: "No, cancel")
 * @param {string} config.confirmButtonClass - CSS class for confirm button (default: "btn-danger")
 * @param {string} config.icon - Icon name: 'warning', 'danger', 'info', 'success', 'question' (default: "warning")
 * @param {Function} config.onConfirm - Callback function to execute on confirmation
 * @param {Object} config.context - Context data to pass to the callback
 */
function openConfirmationModal(config = {}) {
    // Set defaults
    const defaults = {
        title: 'Confirm Action',
        message: 'Are you sure you want to perform this action?',
        detail: '',
        confirmText: 'Yes, I\'m sure',
        cancelText: 'No, cancel',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: null,
        context: null
    };
    
    const settings = { ...defaults, ...config };
    
    // Store callback and context for later execution
    confirmationCallback = settings.onConfirm;
    confirmationContext = settings.context;
    
    // Get DOM elements
    const modal = document.getElementById('confirmationModal');
    const titleEl = document.getElementById('confirmModalTitle');
    const messageEl = document.getElementById('confirmModalMessage');
    const detailEl = document.getElementById('confirmModalDetail');
    const btn = document.getElementById('confirmModalBtn');
    const btnText = document.getElementById('confirmModalBtnText');
    const iconContainer = document.getElementById('confirmModalIcon');
    
    // Update content
    if (titleEl) titleEl.textContent = settings.title;
    if (messageEl) messageEl.textContent = settings.message;
    if (detailEl) {
        if (settings.detail) {
            detailEl.textContent = settings.detail;
            detailEl.style.display = 'block';
        } else {
            detailEl.style.display = 'none';
        }
    }
    if (btnText) btnText.textContent = settings.confirmText;
    
    // Update button class
    if (btn) {
        // Remove all button classes
        btn.className = 'text-sm px-5 py-2.5 rounded-lg transition flex items-center justify-center gap-2';
        // Add the specified class
        btn.classList.add(settings.confirmButtonClass);
    }
    
    // Update icon
    if (iconContainer) {
        const iconMap = {
            warning: {
                bg: 'var(--color-warning)',
                icon: 'alert-triangle'
            },
            danger: {
                bg: 'var(--color-error)',
                icon: 'x-circle'
            },
            info: {
                bg: 'var(--color-info)',
                icon: 'info'
            },
            success: {
                bg: 'var(--color-success)',
                icon: 'check-circle'
            },
            question: {
                bg: 'var(--color-primary-solid)',
                icon: 'help-circle'
            }
        };
        
        const iconConfig = iconMap[settings.icon] || iconMap.warning;
        iconContainer.style.backgroundColor = iconConfig.bg;
        
        // Update icon SVG
        const iconMapSvg = {
            'alert-triangle': `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
            'x-circle': `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`,
            'info': `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`,
            'check-circle': `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white"><circle cx="12" cy="12" r="10"></circle><path d="M9 12l2 2 4-4"></path></svg>`,
            'help-circle': `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-white"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`
        };
        iconContainer.innerHTML = iconMapSvg[iconConfig.icon] || iconMapSvg['alert-triangle'];
    }
    
    // Show modal with animation
    modal.classList.remove('hidden');
    modal.style.opacity = '0';
    modal.style.transition = 'opacity 0.2s ease';
    requestAnimationFrame(() => {
        modal.style.opacity = '1';
    });
    document.body.style.overflow = 'hidden';
}

/**
 * Close the confirmation modal
 */
function closeConfirmationModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById('confirmationModal');
    modal.style.opacity = '0';
    setTimeout(() => {
        modal.classList.add('hidden');
    }, 200);
    document.body.style.overflow = '';
    confirmationCallback = null;
    confirmationContext = null;
}

/**
 * Execute the confirmed action
 */
function executeConfirmedAction() {
    if (typeof confirmationCallback === 'function') {
        if (confirmationContext !== null) {
            confirmationCallback(confirmationContext);
        } else {
            confirmationCallback();
        }
    }
    closeConfirmationModal();
}

// Close on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeConfirmationModal();
    }
});

// ================================================================
// ACTION-SPECIFIC CONFIRMATION FUNCTIONS
// ================================================================

/**
 * Confirm Logout
 */
function confirmLogout() {
    openConfirmationModal({
        title: 'Logout Confirmation',
        message: 'Are you sure you want to log out of your account?',
        detail: 'You will need to enter your credentials again to access your dashboard.',
        confirmText: 'Yes, log me out',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: function() {
            document.getElementById('logoutForm').submit();
        }
    });
}

/**
 * Confirm Ticket Resolution
 * @param {string} ticketId - The ticket ID or number
 * @param {string} ticketTitle - The ticket title
 * @param {Function} onConfirm - Callback function
 */
function confirmResolveTicket(ticketId, ticketTitle, onConfirm) {
    openConfirmationModal({
        title: 'Resolve Ticket',
        message: `Are you sure you want to resolve "${ticketTitle}"?`,
        detail: 'This will mark the ticket as resolved and notify the requester.',
        confirmText: 'Yes, resolve it',
        confirmButtonClass: 'btn-success',
        icon: 'success',
        onConfirm: onConfirm,
        context: { ticketId, ticketTitle }
    });
}

/**
 * Confirm Ticket Closure
 * @param {string} ticketId - The ticket ID or number
 * @param {string} ticketTitle - The ticket title
 * @param {Function} onConfirm - Callback function
 */
function confirmCloseTicket(ticketId, ticketTitle, onConfirm) {
    openConfirmationModal({
        title: 'Close Ticket',
        message: `Are you sure you want to close "${ticketTitle}"?`,
        detail: 'This ticket will be closed and no further updates will be accepted.',
        confirmText: 'Yes, close it',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: onConfirm,
        context: { ticketId, ticketTitle }
    });
}

/**
 * Confirm Ticket Escalation
 * @param {string} ticketId - The ticket ID or number
 * @param {string} ticketTitle - The ticket title
 * @param {string} escalateTo - Who/where it's being escalated to
 * @param {Function} onConfirm - Callback function
 */
function confirmEscalateTicket(ticketId, ticketTitle, escalateTo, onConfirm) {
    openConfirmationModal({
        title: 'Escalate Ticket',
        message: `Are you sure you want to escalate "${ticketTitle}"?`,
        detail: `This ticket will be escalated to ${escalateTo} for review.`,
        confirmText: 'Yes, escalate it',
        confirmButtonClass: 'btn-warning',
        icon: 'danger',
        onConfirm: onConfirm,
        context: { ticketId, ticketTitle, escalateTo }
    });
}

/**
 * Confirm Article Archive
 * @param {string} articleTitle - The article's title
 * @param {string} formId - id of the (already-rendered) form to submit on confirm
 */
function confirmArchiveArticle(articleTitle, formId) {
    openConfirmationModal({
        title: 'Archive Article',
        message: `Are you sure you want to archive "${articleTitle}"?`,
        detail: 'It will be removed from the Knowledge Base until restored. You can restore it anytime from the Archived tab.',
        confirmText: 'Yes, archive it',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: function() {
            document.getElementById(formId).submit();
        }
    });
}

/**
 * Confirm Article Restore
 * @param {string} articleTitle - The article's title
 * @param {string} restoreToStatus - Display label of the status it will return to (e.g. "Published")
 * @param {string} formId - id of the (already-rendered) form to submit on confirm
 */
function confirmRestoreArticle(articleTitle, restoreToStatus, formId) {
    openConfirmationModal({
        title: 'Restore Article',
        message: `Are you sure you want to restore "${articleTitle}"?`,
        detail: `It will go back to ${restoreToStatus}.`,
        confirmText: 'Yes, restore it',
        confirmButtonClass: 'btn-success',
        icon: 'success',
        onConfirm: function() {
            document.getElementById(formId).submit();
        }
    });
}

/**
 * Confirm Delete
 * @param {string} itemName - Name of the item being deleted
 * @param {string} itemType - Type of item (e.g., "Ticket", "User", "Asset")
 * @param {Function} onConfirm - Callback function
 */
function confirmDelete(itemName, itemType = 'item', onConfirm) {
    openConfirmationModal({
        title: `Delete ${itemType}`,
        message: `Are you sure you want to delete "${itemName}"?`,
        detail: 'This action cannot be undone. All associated data will be permanently removed.',
        confirmText: 'Yes, delete it',
        confirmButtonClass: 'btn-danger',
        icon: 'danger',
        onConfirm: onConfirm,
        context: { itemName, itemType }
    });
}

/**
 * Confirm User Deactivation
 * @param {string} userName - The user's name
 * @param {Function} onConfirm - Callback function
 */
function confirmDeactivateUser(userName, onConfirm) {
    openConfirmationModal({
        title: 'Deactivate User',
        message: `Are you sure you want to deactivate "${userName}"?`,
        detail: 'This user will lose access to the system until reactivated.',
        confirmText: 'Yes, deactivate',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: onConfirm,
        context: { userName }
    });
}

/**
 * Confirm Asset Assignment
 * @param {string} assetName - The asset name
 * @param {string} assignTo - Who it's being assigned to
 * @param {Function} onConfirm - Callback function
 */
function confirmAssignAsset(assetName, assignTo, onConfirm) {
    openConfirmationModal({
        title: 'Assign Asset',
        message: `Are you sure you want to assign "${assetName}"?`,
        detail: `This asset will be assigned to ${assignTo}.`,
        confirmText: 'Yes, assign it',
        confirmButtonClass: 'btn-primary',
        icon: 'info',
        onConfirm: onConfirm,
        context: { assetName, assignTo }
    });
}

/**
 * Confirm Bulk Action
 * @param {string} action - The action (e.g., "delete", "assign", "resolve")
 * @param {number} count - Number of items affected
 * @param {Function} onConfirm - Callback function
 */
function confirmBulkAction(action, count, onConfirm) {
    const actionMap = {
        'assign': { text: 'Assign', class: 'btn-primary', icon: 'info' },
        'resolve': { text: 'Resolve', class: 'btn-success', icon: 'success' },
        'delete': { text: 'Delete', class: 'btn-danger', icon: 'danger' },
        'escalate': { text: 'Escalate', class: 'btn-warning', icon: 'warning' },
        'close': { text: 'Close', class: 'btn-danger', icon: 'warning' }
    };
    
    const config = actionMap[action] || { 
        text: action.charAt(0).toUpperCase() + action.slice(1), 
        class: 'btn-primary', 
        icon: 'info' 
    };
    
    openConfirmationModal({
        title: `Confirm ${config.text}`,
        message: `Are you sure you want to ${action} ${count} selected item(s)?`,
        detail: `This will ${action} ${count} item(s). This action cannot be undone.`,
        confirmText: `Yes, ${action} ${count}`,
        confirmButtonClass: config.class,
        icon: config.icon,
        onConfirm: onConfirm,
        context: { action, count }
    });
}

/**
 * Generic status change confirmation
 * @param {string} status - The new status
 * @param {string} itemName - Name of the item
 * @param {Function} onConfirm - Callback function
 */
function confirmStatusChange(status, itemName, onConfirm) {
    const statusMap = {
        'RESOLVED': { text: 'Resolve', class: 'btn-success', icon: 'success' },
        'CLOSED': { text: 'Close', class: 'btn-danger', icon: 'warning' },
        'ESCALATED': { text: 'Escalate', class: 'btn-warning', icon: 'danger' },
        'APPROVED': { text: 'Approve', class: 'btn-success', icon: 'success' },
        'REJECTED': { text: 'Reject', class: 'btn-danger', icon: 'danger' },
        'IN_PROGRESS': { text: 'Start Progress', class: 'btn-primary', icon: 'info' },
        'COMPLETED': { text: 'Complete', class: 'btn-success', icon: 'success' },
        'PUBLISHED': { text: 'Publish', class: 'btn-success', icon: 'success' },
        'CANCELLED': { text: 'Cancel', class: 'btn-danger', icon: 'warning' }
    };
    
    const config = statusMap[status] || { 
        text: status.charAt(0).toUpperCase() + status.slice(1), 
        class: 'btn-primary', 
        icon: 'info' 
    };
    
    openConfirmationModal({
        title: `Confirm ${config.text}`,
        message: `Are you sure you want to ${config.text.toLowerCase()} "${itemName}"?`,
        detail: `The status will be updated to ${status.replace('_', ' ')}.`,
        confirmText: `Yes, ${config.text.toLowerCase()}`,
        confirmButtonClass: config.class,
        icon: config.icon,
        onConfirm: onConfirm,
        context: { status, itemName }
    });
}

/**
 * Confirm a Team Lead review decision on a ticket (approve / reject / request changes)
 * @param {string} action - 'approve' | 'reject' | 'request_changes'
 * @param {Function} onConfirm - Callback function
 */
function confirmReviewDecision(action, onConfirm) {
    const actionMap = {
        'approve': { text: 'Approve', class: 'btn-success', icon: 'success', detail: 'This ticket will move forward in the workflow.' },
        'reject': { text: 'Reject', class: 'btn-danger', icon: 'danger', detail: 'This ticket will be rejected based on your comment.' },
        'request_changes': { text: 'Request Changes', class: 'btn-warning', icon: 'warning', detail: 'The requester will be asked to revise the ticket based on your comment.' }
    };
    const config = actionMap[action] || { text: action, class: 'btn-primary', icon: 'info', detail: '' };

    openConfirmationModal({
        title: `Confirm ${config.text}`,
        message: `Are you sure you want to ${config.text.toLowerCase()} this ticket?`,
        detail: config.detail,
        confirmText: `Yes, ${config.text.toLowerCase()}`,
        confirmButtonClass: config.class,
        icon: config.icon,
        onConfirm: onConfirm,
        context: { action }
    });
}

/**
 * Confirm approving a service request
 * @param {string} itemName - The request's title/identifier
 * @param {Function} onConfirm - Callback function
 */
function confirmApproveRequest(itemName, onConfirm) {
    openConfirmationModal({
        title: 'Approve Request',
        message: `Are you sure you want to approve "${itemName}"?`,
        detail: 'This request will move forward in the workflow.',
        confirmText: 'Yes, approve',
        confirmButtonClass: 'btn-success',
        icon: 'success',
        onConfirm: onConfirm,
        context: { itemName }
    });
}

/**
 * Confirm revoking a document/folder share
 * @param {string} target - Who the share was granted to
 * @param {Function} onConfirm - Callback function
 */
function confirmRevokeAccess(target, onConfirm) {
    openConfirmationModal({
        title: 'Revoke Access',
        message: `Revoke access for ${target}?`,
        detail: 'They will immediately lose the ability to view this content.',
        confirmText: 'Yes, revoke it',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: onConfirm
    });
}

/**
 * Generic reject-with-reason confirmation (remote sessions, etc.)
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @param {Function} onConfirm - Callback function
 */
function confirmReject(title, message, onConfirm) {
    openConfirmationModal({
        title: title,
        message: message,
        confirmText: 'Yes, reject',
        confirmButtonClass: 'btn-danger',
        icon: 'danger',
        onConfirm: onConfirm
    });
}

/**
 * Generic end-session confirmation (remote sessions)
 * @param {Function} onConfirm - Callback function
 */
function confirmEndSession(onConfirm) {
    openConfirmationModal({
        title: 'End Remote Session',
        message: 'Are you sure you want to end this remote session?',
        detail: 'The connection will be closed for both parties.',
        confirmText: 'Yes, end session',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: onConfirm
    });
}

/**
 * Confirm leaving a page with unsaved changes (e.g. the KB article editor).
 * Used for in-app navigation we control (a Cancel link, sidebar clicks) —
 * the browser's native beforeunload dialog is the only option for tab
 * close/refresh/back, which can't be replaced with a custom modal.
 * @param {Function} onConfirm - Callback function, called if the user chooses to discard
 */
function confirmDiscardChanges(onConfirm) {
    openConfirmationModal({
        title: 'Unsaved Changes',
        message: 'You have unsaved changes. Leave without saving?',
        detail: 'Anything you\'ve typed since your last Save will be lost.',
        confirmText: 'Discard changes',
        confirmButtonClass: 'btn-danger',
        icon: 'warning',
        onConfirm: onConfirm
    });
}

/**
 * Confirm renewing a license/subscription asset
 * @param {string} assetName - The asset name
 * @param {Function} onConfirm - Callback function
 */
function confirmRenewAsset(assetName, onConfirm) {
    openConfirmationModal({
        title: 'Mark as Renewed',
        message: `Confirm "${assetName}" has been renewed?`,
        detail: 'The next renewal date will advance by this asset\'s renewal interval, and this is logged for audit.',
        confirmText: 'Yes, mark renewed',
        confirmButtonClass: 'btn-success',
        icon: 'success',
        onConfirm: onConfirm
    });
}

// ================================================================
// EXPOSE GLOBALLY FOR USE IN HTML ONCLICK ATTRIBUTES
// ================================================================

window.openConfirmationModal = openConfirmationModal;
window.closeConfirmationModal = closeConfirmationModal;
window.executeConfirmedAction = executeConfirmedAction;
window.confirmLogout = confirmLogout;
window.confirmArchiveArticle = confirmArchiveArticle;
window.confirmRestoreArticle = confirmRestoreArticle;
window.confirmDelete = confirmDelete;
window.confirmResolveTicket = confirmResolveTicket;
window.confirmCloseTicket = confirmCloseTicket;
window.confirmEscalateTicket = confirmEscalateTicket;
window.confirmDeactivateUser = confirmDeactivateUser;
window.confirmAssignAsset = confirmAssignAsset;
window.confirmBulkAction = confirmBulkAction;
window.confirmStatusChange = confirmStatusChange;
window.confirmReviewDecision = confirmReviewDecision;
window.confirmApproveRequest = confirmApproveRequest;
window.confirmRenewAsset = confirmRenewAsset;
window.confirmReject = confirmReject;
window.confirmEndSession = confirmEndSession;
window.confirmDiscardChanges = confirmDiscardChanges;
window.confirmRevokeAccess = confirmRevokeAccess;