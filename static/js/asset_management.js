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
    console.log('🔵 Asset management initialized');
    console.log('🔵 URLs:', {
        assetReassignModalUrl,
        scrapApproveModalUrl,
        scrapRequestModalUrl,
        editUrl,
        assetsUrl
    });
}

// ================================================================
// SCRAP APPROVE MODAL
// ================================================================

function openScrapApproveModal(assetId) {
    console.log('🔵 openScrapApproveModal called with assetId:', assetId);
    
    if (!scrapApproveModalUrl) {
        console.error('❌ scrapApproveModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = scrapApproveModalUrl.replace('0', assetId);
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    console.log('🔵 Loading scrap approve modal from:', url);
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            console.log('🔵 Scrap approve modal loaded');
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
    console.log('🔵 openScrapRequestModal called with assetId:', assetId);
    
    if (!scrapRequestModalUrl) {
        console.error('❌ scrapRequestModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = scrapRequestModalUrl.replace('0', assetId);
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    console.log('🔵 Loading scrap request modal from:', url);
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            console.log('🔵 Scrap request modal loaded');
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
    console.log('🔵 openAssetReassignModal called with assetId:', assetId);
    
    if (!assetReassignModalUrl) {
        console.error('❌ assetReassignModalUrl is not set');
        if (typeof showToast === 'function') {
            showToast('Configuration error. Please refresh the page.', 'error');
        }
        return;
    }
    
    const url = assetReassignModalUrl.replace('0', assetId);
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    
    if (!overlay || !container) {
        console.error('❌ Modal elements not found');
        return;
    }
    
    console.log('🔵 Loading reassign modal from:', url);
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    
    htmx.ajax('GET', url, {
        target: '#modalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            console.log('🔵 Reassign modal loaded');
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

function closeModal() {
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
    
    const url = editUrl.replace('0', assetId);
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
    
    form.querySelectorAll('input, select').forEach(function(el) {
        if (el.tagName === 'INPUT') {
            el.value = '';
        } else if (el.tagName === 'SELECT') {
            el.selectedIndex = 0;
        }
    });
    
    if (assetsUrl) {
        htmx.ajax('GET', assetsUrl, {
            target: '#assetTableContainer',
            swap: 'innerHTML'
        });
    }
}

// ================================================================
// EXPORT DROPDOWN
// ================================================================

function toggleExportDropdown() {
    const dropdown = document.getElementById('exportDropdown');
    if (dropdown) {
        dropdown.classList.toggle('hidden');
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
    
    console.log('🔵 Asset management JS initialized');
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

// Modal close function
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.remove();
    }
    const overlay = document.getElementById('modalOverlay');
    const container = document.getElementById('modalContainer');
    if (overlay) overlay.classList.add('hidden');
    if (container) container.innerHTML = '';
}