// static/js/asset_management.js
// ================================================================
// ASSET MANAGEMENT - All asset-related JavaScript
// ================================================================

// Global variables (set from template)
let assetReassignModalUrl = '';
let scrapApproveModalUrl = '';
let scrapRequestModalUrl = '';
let editUrl = '';
let assetsUrl = '';

// ================================================================
// INITIALIZATION
// ================================================================

function initAssetManagement(config) {
    assetReassignModalUrl = config.assetReassignModalUrl || '';
    scrapApproveModalUrl = config.scrapApproveModalUrl || '';
    scrapRequestModalUrl = config.scrapRequestModalUrl || '';
    editUrl = config.editUrl || '';
    assetsUrl = config.assetsUrl || '';
}

// ================================================================
// SCRAP APPROVE MODAL
// ================================================================

function openScrapApproveModal(assetId) {
    if (!scrapApproveModalUrl) {
        console.error('❌ scrapApproveModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = scrapApproveModalUrl.replace('/0/', '/' + assetId + '/');
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            overlay.classList.remove('hidden');
        },
        onError: function(error) {
            console.error('❌ Failed to load scrap approve modal:', error);
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load modal. Please try again.</div>';
            if (typeof showToast === 'function') {
                showToast('Failed to load scrap approve modal.', 'error');
            }
        }
    });
}

// ================================================================
// SCRAP REQUEST MODAL
// ================================================================

function openScrapRequestModal(assetId) {
    if (!scrapRequestModalUrl) {
        console.error('❌ scrapRequestModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = scrapRequestModalUrl.replace('/0/', '/' + assetId + '/');
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            overlay.classList.remove('hidden');
        },
        onError: function(error) {
            console.error('❌ Failed to load scrap request modal:', error);
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load modal. Please try again.</div>';
            if (typeof showToast === 'function') {
                showToast('Failed to load scrap request modal.', 'error');
            }
        }
    });
}

// ================================================================
// ASSET REASSIGN MODAL
// ================================================================

function openAssetReassignModal(assetId) {
    if (!assetReassignModalUrl) {
        console.error('❌ assetReassignModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = assetReassignModalUrl.replace('/0/', '/' + assetId + '/');
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            overlay.classList.remove('hidden');
        },
        onError: function(error) {
            console.error('❌ Failed to load reassign modal:', error);
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load modal. Please try again.</div>';
            if (typeof showToast === 'function') {
                showToast('Failed to load reassign modal.', 'error');
            }
        }
    });
}

// ================================================================
// CLOSE MODAL
// ================================================================

function closeModal(modalId) {
    if (modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.remove();
    }
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    if (overlay) {
        overlay.classList.add('hidden');
    }
    if (container) {
        setTimeout(function() {
            container.innerHTML = '';
        }, 150);
    }
}

function closeAssetReassignModal() {
    closeModal();
}

// ================================================================
// EDIT ASSET
// ================================================================

function editAsset(assetId) {
    if (!editUrl) {
        console.error('❌ editUrl is not set');
        return;
    }
    
    const url = editUrl.replace('/0/', '/' + assetId + '/');
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onError: function() {
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load edit form.</div>';
        }
    });
}

// ================================================================
// FILTERS
// ================================================================

function resetFilters(event) {
    if (event) event.preventDefault();
    const form = document.getElementById('assetFilters');
    if (!form) return;

    // The Licenses & Subscriptions tab reuses this same form id/reset
    // button but has its own filter set — its hidden filter_tab field (see
    // asset_license_panel.html) is how we tell the two apart and keep
    // Reset scoped to whichever tab's form is currently on screen instead
    // of always falling back to Equipment.
    const tabField = form.querySelector('input[name="filter_tab"]');
    const tab = tabField ? tabField.value : null;

    form.querySelectorAll('input, select').forEach(function(el) {
        if (el.name === 'filter_tab') return;
        if (el.tagName === 'INPUT') {
            if (el.type === 'checkbox' || el.type === 'radio') {
                // Group by owner defaults to ON (unlike the other filter
                // checkboxes, which default to off/unfiltered) — Reset
                // should return to that default, not force it off.
                el.checked = el.name === 'filter_group_by_owner';
            } else {
                el.value = '';
            }
        } else if (el.tagName === 'SELECT') {
            el.selectedIndex = 0;
        }
    });

    if (assetsUrl) {
        const url = tab ? (assetsUrl + '?filter_tab=' + encodeURIComponent(tab)) : assetsUrl;
        htmx.ajax('GET', url, {
            target: '#assetTableContainer',
            swap: 'innerHTML'
        });
    }
}

// ================================================================
// EXPORT DROPDOWN
// ================================================================

let exportDropdownCleanup = null;

function toggleExportDropdown() {
    const dropdown = document.getElementById('exportDropdown');
    if (!dropdown) return;
    if (dropdown.classList.contains('hidden')) {
        dropdown.classList.remove('hidden');
        const trigger = document.querySelector('[onclick="toggleExportDropdown()"]');
        if (trigger && window.positionDropdown) {
            exportDropdownCleanup = window.positionDropdown(trigger, dropdown, { align: 'right' });
        }
    } else {
        dropdown.classList.add('hidden');
        if (exportDropdownCleanup) {
            exportDropdownCleanup();
            exportDropdownCleanup = null;
        }
    }
}

function closeImportModal() {
    const modal = document.getElementById('importModal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

// ================================================================
// LISTENERS
// ================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Close export dropdown on outside click
    document.addEventListener('click', function(event) {
        const dropdown = document.getElementById('exportDropdown');
        const button = document.querySelector('[onclick="toggleExportDropdown()"]');
        if (dropdown && button && !dropdown.contains(event.target) && !button.contains(event.target)) {
            dropdown.classList.add('hidden');
            if (exportDropdownCleanup) {
                exportDropdownCleanup();
                exportDropdownCleanup = null;
            }
        }
    });
    
    // Close modals on escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeModal();
        }
    });
    
    // Handle closeModal events from HTMX
    document.addEventListener('closeModal', function() {
        closeModal();
    });
    
});

// ================================================================
// ASSET CHECK-IN/CHECK-OUT
// ================================================================

function openCheckoutModal(assetId) {
    const url = `/tickets/assets/${assetId}/checkout-modal/`;
    const container = document.getElementById('modalContainer');
    const overlay = document.getElementById('modalOverlay');
    
    if (!container || !overlay) return;
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onError: function() {
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load checkout form.</div>';
        }
    });
}

function openCheckinModal(assetId) {
    const url = `/tickets/assets/${assetId}/checkin-modal/`;
    const container = document.getElementById('modalContainer');
    const overlay = document.getElementById('modalOverlay');
    
    if (!container || !overlay) return;
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onError: function() {
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load checkin form.</div>';
        }
    });
}

function openCheckoutHistory(assetId) {
    const url = `/tickets/assets/${assetId}/checkout-history/`;
    const container = document.getElementById('modalContainer');
    const overlay = document.getElementById('modalOverlay');
    
    if (!container || !overlay) return;
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onError: function() {
            container.innerHTML = '<div class="p-6 text-center text-error">Failed to load history.</div>';
        }
    });
}

// closeModal(modalId) is defined once, above, and handles both the
// no-arg case (asset_list.html, scrap modals) and the modalId case
// (checkout/checkin modals).