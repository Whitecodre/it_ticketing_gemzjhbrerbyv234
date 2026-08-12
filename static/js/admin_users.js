// admin_users.js – Admin User Management

// ================================================================
// MODAL FUNCTIONS
// ================================================================

// --- Create Modal ---
function generatePasswordPreview() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%';
    let pwd = '';
    for (let i = 0; i < 12; i++) {
        pwd += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return pwd;
}

function regenerateCreatePasswordPreview() {
    const field = document.getElementById('CreatePassword');
    if (field) field.value = generatePasswordPreview();
}

function openCreateModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        regenerateCreatePasswordPreview();
    }
}

function closeCreateModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
        const form = document.getElementById('createUserForm');
        if (form) form.reset();
    }
}

// --- Edit Modal ---
function openEditModal(userId) {
    const row = document.querySelector(`tr[data-user-id="${userId}"]`);
    if (!row) return;
    
    document.getElementById('editUserId').value = userId;
    document.getElementById('editEmail').value = row.dataset.email;
    document.getElementById('editFirstName').value = row.dataset.firstName;
    document.getElementById('editLastName').value = row.dataset.lastName;
    document.getElementById('editPosition').value = row.dataset.position || '';
    
    // Set primary role
    const primaryRole = row.dataset.role || '';
    document.getElementById('editPrimaryRole').value = primaryRole;
    
    // Set department
    document.getElementById('editDepartment').value = row.dataset.department || '';
    document.getElementById('editIsActive').checked = row.dataset.isActive === 'true';

    // Handle additional roles checkboxes
    const roleCheckboxes = document.querySelectorAll('#editRolesCheckboxes input[name="selected_roles"]');
    roleCheckboxes.forEach(checkbox => { checkbox.checked = false; });
    const assignedRoles = row.dataset.assignedRoles ? row.dataset.assignedRoles.split(',') : [];
    roleCheckboxes.forEach(checkbox => {
        checkbox.checked = assignedRoles.includes(checkbox.value);
    });

    // Update checkbox states based on primary role
    updateRoleCheckboxes('editRolesCheckboxes', 'editPrimaryRole');
    
    const modal = document.getElementById('editUserModal');
    if (modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
}

function closeEditModal() { 
    const modal = document.getElementById('editUserModal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

// --- Password Modal ---
function openPasswordModal(userId) {
    var row = document.querySelector('tr[data-user-id="' + userId + '"]');
    if (!row) return;

    document.getElementById('passwordUserId').value = userId;

    var firstName = row.dataset.firstName || '';
    var lastName = row.dataset.lastName || '';
    var fullName = (firstName + ' ' + lastName).trim() || row.dataset.email || '';
    var role = row.dataset.role || '';
    var department = row.dataset.department || '';

    // Auto-generate initials
    var initials = (firstName.charAt(0) || '') + (lastName.charAt(0) || '');
    if (!initials) {
        initials = row.dataset.email ? row.dataset.email.charAt(0).toUpperCase() : 'U';
    }
    document.getElementById('passwordUserInitials').textContent = initials.toUpperCase();
    document.getElementById('passwordUserName').textContent = fullName;
    document.getElementById('passwordUserDetails').textContent = 
        'Role: ' + (row.dataset.assignedRoles || role) + ' | Department: ' + (department || 'None');

    const modal = document.getElementById('changePasswordModal');
    if (modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
}

function closePasswordModal() {
    var modal = document.getElementById('changePasswordModal');
    if (!modal) return;
    modal.classList.add('hidden');
    document.body.style.overflow = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmPassword').value = '';
    
    var newPwd = document.getElementById('newPassword');
    var confirmPwd = document.getElementById('confirmPassword');
    if (newPwd) newPwd.type = 'password';
    if (confirmPwd) confirmPwd.type = 'password';
    
    var newEye = document.getElementById('pwdNewEyeIcon');
    var newEyeOff = document.getElementById('pwdNewEyeOffIcon');
    var confirmEye = document.getElementById('pwdConfirmEyeIcon');
    var confirmEyeOff = document.getElementById('pwdConfirmEyeOffIcon');
    if (newEye) newEye.classList.remove('hidden');
    if (newEyeOff) newEyeOff.classList.add('hidden');
    if (confirmEye) confirmEye.classList.remove('hidden');
    if (confirmEyeOff) confirmEyeOff.classList.add('hidden');
}

// --- Impersonate Modal ---
function openImpersonateModal(userId, userName) {
    window.impersonateUserId = userId;
    window.impersonateUserName = userName;
    
    const overlay = document.getElementById('impersonateModalOverlay');
    const container = document.getElementById('impersonateModalContainer');
    
    if (!overlay || !container) return;
    
    container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
    overlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    
    htmx.ajax('GET', `/accounts/impersonate/modal/?user_id=${userId}&user_name=${encodeURIComponent(userName)}`, {
        target: '#impersonateModalContainer',
        swap: 'innerHTML',
        onAfterSwap: function() {
            const userIdInput = document.getElementById('impersonateUserId');
            if (userIdInput) {
                userIdInput.value = userId;
            }
            const nameElement = document.getElementById('impersonateUserName');
            if (nameElement && userName) {
                nameElement.textContent = userName;
            }
            initImpersonateReasonHandler();
        }
    });
}

function closeImpersonateModal() {
    const overlay = document.getElementById('impersonateModalOverlay');
    const container = document.getElementById('impersonateModalContainer');
    if (overlay) overlay.classList.add('hidden');
    if (container) container.innerHTML = '';
    document.body.style.overflow = '';
}

// ================================================================
// ROLE CHECKBOX SYNC
// ================================================================

function updateRoleCheckboxes(containerId, primaryRoleSelectId) {
    const container = document.getElementById(containerId);
    const primarySelect = document.getElementById(primaryRoleSelectId);
    if (!container || !primarySelect) return;
    
    const primaryValue = primarySelect.value;
    
    container.querySelectorAll('.additional-role-checkbox').forEach(checkbox => {
        const checkboxValue = checkbox.dataset.roleName || checkbox.value;
        
        if (checkboxValue === primaryValue) {
            checkbox.disabled = true;
            checkbox.checked = false;
            checkbox.closest('.role-checkbox').style.opacity = '0.4';
            checkbox.closest('.role-checkbox').style.cursor = 'not-allowed';
        } else {
            checkbox.disabled = false;
            checkbox.closest('.role-checkbox').style.opacity = '1';
            checkbox.closest('.role-checkbox').style.cursor = 'pointer';
        }
    });
}

function initRoleCheckboxes(containerId, primaryRoleSelectId) {
    const container = document.getElementById(containerId);
    const primarySelect = document.getElementById(primaryRoleSelectId);
    if (!container || !primarySelect) return;
    
    primarySelect.addEventListener('change', function() {
        updateRoleCheckboxes(containerId, primaryRoleSelectId);
    });
    
    // Initial sync
    updateRoleCheckboxes(containerId, primaryRoleSelectId);
}

// ================================================================
// TOGGLE PASSWORD VISIBILITY
// ================================================================

function togglePasswordVisibility(inputId, eyeId, eyeOffId) {
    var input = document.getElementById(inputId);
    var eye = document.getElementById(eyeId);
    var eyeOff = document.getElementById(eyeOffId);
    if (!input || !eye || !eyeOff) return;
    if (input.type === 'password') {
        input.type = 'text';
        eye.classList.add('hidden');
        eyeOff.classList.remove('hidden');
    } else {
        input.type = 'password';
        eye.classList.remove('hidden');
        eyeOff.classList.add('hidden');
    }
}

// ================================================================
// IMPERSONATE REASON HANDLER
// ================================================================

function initImpersonateReasonHandler() {
    const reasonSelect = document.getElementById('impersonateReason');
    const otherContainer = document.getElementById('otherReasonContainer');
    const otherInput = document.getElementById('otherReason');
    
    if (reasonSelect) {
        reasonSelect.removeEventListener('change', handleReasonChange);
        reasonSelect.addEventListener('change', handleReasonChange);
    }
}

function handleReasonChange() {
    const reasonSelect = document.getElementById('impersonateReason');
    const otherContainer = document.getElementById('otherReasonContainer');
    const otherInput = document.getElementById('otherReason');
    
    if (!reasonSelect || !otherContainer) return;
    
    if (reasonSelect.value === 'Other') {
        otherContainer.style.display = 'block';
        if (otherInput) otherInput.required = true;
    } else {
        otherContainer.style.display = 'none';
        if (otherInput) otherInput.required = false;
    }
}

// ================================================================
// FORM SUBMISSIONS
// ================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize role checkboxes for create modal
    initRoleCheckboxes('createRolesCheckboxes', 'createPrimaryRole');
    // Initialize role checkboxes for edit modal
    initRoleCheckboxes('editRolesCheckboxes', 'editPrimaryRole');

    // --- Create User Form ---
    const createForm = document.getElementById('createUserForm');
    if (createForm) {
        createForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const form = this;
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;
            const formData = new FormData(form);
            form.querySelectorAll('input[name="selected_roles"]').forEach(checkbox => {
                if (checkbox.checked) formData.append('selected_roles', checkbox.value);
            });
            fetch(form.action, {
                method: 'POST',
                headers: { 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value },
                body: formData
            }).then(response => response.json())
                .then(data => {
                    if (data.status === 'ok') {
                        closeCreateModal();
                        form.reset();
                        refreshTable();
                        if (typeof showToast === 'function') {
                            showToast('User created successfully');
                        }
                    } else {
                        if (typeof showToast === 'function') {
                            showToast(data.error || 'Error creating user', 'error');
                        }
                    }
                })
                .catch(error => {
                    console.error('Create user error:', error);
                    if (typeof showToast === 'function') {
                        showToast('Network error. Please try again.', 'error');
                    }
                })
                .finally(() => {
                    if (submitBtn) submitBtn.disabled = false;
                });
        });
    }

    // --- Edit User Form ---
    const editForm = document.getElementById('editUserForm');
    if (editForm) {
        editForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const submitBtn = editForm.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;
            const userId = document.getElementById('editUserId').value;
            const formData = new FormData();
            formData.append('first_name', document.getElementById('editFirstName').value);
            formData.append('last_name', document.getElementById('editLastName').value);
            formData.append('position', document.getElementById('editPosition').value || '');
            formData.append('role', document.getElementById('editPrimaryRole').value);
            formData.append('department', document.getElementById('editDepartment').value);
            formData.append('is_active', document.getElementById('editIsActive').checked);
            document.querySelectorAll('#editRolesCheckboxes input[name="selected_roles"]').forEach(checkbox => {
                if (checkbox.checked) formData.append('selected_roles', checkbox.value);
            });
            fetch(window.adminUserEditUrl.replace('0', userId), {
                method: 'POST',
                headers: { 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value },
                body: new URLSearchParams(formData)
            }).then(response => response.json())
                .then(data => {
                    if (data.status === 'ok') {
                        closeEditModal();
                        refreshTable();
                        if (typeof showToast === 'function') {
                            showToast('User details updated');
                        }
                    } else {
                        if (typeof showToast === 'function') {
                            showToast(data.error || 'Error updating user', 'error');
                        }
                    }
                })
                .catch(error => {
                    console.error('Edit user error:', error);
                    if (typeof showToast === 'function') {
                        showToast('Network error. Please try again.', 'error');
                    }
                })
                .finally(() => {
                    if (submitBtn) submitBtn.disabled = false;
                });
        });
    }

    // --- Change Password Form ---
    const changePwdForm = document.getElementById('changePasswordForm');
    if (changePwdForm) {
        changePwdForm.addEventListener('submit', function(e) {
            e.preventDefault();
            var userId = document.getElementById('passwordUserId').value;
            var password = document.getElementById('newPassword').value;
            var confirm = document.getElementById('confirmPassword').value;

            if (password !== confirm) {
                if (typeof showToast === 'function') {
                    showToast('Passwords do not match.', 'error');
                }
                return;
            }
            if (password.length < 8) {
                if (typeof showToast === 'function') {
                    showToast('Password must be at least 8 characters.', 'error');
                }
                return;
            }

            var submitBtn = changePwdForm.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;

            var url = window.adminUserChangePasswordUrl.replace('0', userId);
            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                },
                body: new URLSearchParams({ password: password })
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.status === 'ok') {
                    closePasswordModal();
                    if (typeof showToast === 'function') {
                        showToast(data.message || 'Password changed successfully');
                    }
                } else {
                    if (typeof showToast === 'function') {
                        showToast(data.error || 'Error changing password', 'error');
                    }
                }
            })
            .catch(function(err) {
                console.error('Password change error:', err);
                if (typeof showToast === 'function') {
                    showToast('Network error. Please try again.', 'error');
                }
            })
            .finally(function() {
                if (submitBtn) submitBtn.disabled = false;
            });
        });
    }

    // --- Impersonate Form (delegated) ---
    document.addEventListener('submit', function(e) {
        if (e.target.id === 'impersonateForm') {
            handleImpersonateSubmit(e);
        }
    });
});

// ================================================================
// TOGGLE ACTIVE
// ================================================================

function toggleActive(userId) {
    fetch(window.adminUserToggleUrl.replace('0', userId), {
        method: 'POST',
        headers: { 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value }
    }).then(response => response.json())
        .then(data => {
            if (data.status === 'ok') {
                refreshTable();
                if (typeof showToast === 'function') {
                    showToast(data.is_active ? 'User activated' : 'User deactivated');
                }
            } else {
                if (typeof showToast === 'function') {
                    showToast(data.error || 'Error toggling user', 'error');
                }
            }
        })
        .catch(error => {
            console.error('Toggle active error:', error);
            if (typeof showToast === 'function') {
                showToast('Network error. Please try again.', 'error');
            }
        });
}

// ================================================================
// REFRESH TABLE
// ================================================================

function refreshTable() {
    const q = document.getElementById('searchInput')?.value || '';
    const role = document.getElementById('roleFilter')?.value || '';
    const dept = document.getElementById('departmentFilter')?.value || '';
    const params = new URLSearchParams({ q, role, department: dept });
    const url = window.adminUsersUrl + '?' + params.toString();
    htmx.ajax('GET', url, { target: '#userTableContainer', swap: 'innerHTML' });
}

// ================================================================
// IMPERSONATE SUBMIT HANDLER
// ================================================================

function handleImpersonateSubmit(e) {
    e.preventDefault();
    
    const userId = document.getElementById('impersonateUserId')?.value || window.impersonateUserId;
    const reasonSelect = document.getElementById('impersonateReason');
    let reason = reasonSelect?.value || '';
    
    if (!userId) {
        if (typeof showToast === 'function') {
            showToast('User ID not found. Please try again.', 'error');
        }
        return;
    }
    
    if (reason === 'Other') {
        reason = document.getElementById('otherReason')?.value?.trim() || '';
        if (!reason) {
            if (typeof showToast === 'function') {
                showToast('Please specify the reason for impersonation.', 'error');
            }
            return;
        }
    }
    
    if (!reason) {
        if (typeof showToast === 'function') {
            showToast('Please select a reason for impersonation.', 'error');
        }
        return;
    }
    
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (!csrfToken) {
        if (typeof showToast === 'function') {
            showToast('Security token missing. Please refresh the page.', 'error');
        }
        return;
    }
    
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const originalHtml = submitBtn?.innerHTML || '';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `
            <span class="inline-flex items-center gap-1">
                <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Logging in...
            </span>
        `;
        submitBtn.classList.add('opacity-70');
    }
    
    fetch(`/accounts/impersonate/${userId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({ reason: reason })
    })
    .then(response => {
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return response.json().then(data => ({ status: response.status, data }));
        } else {
            throw new Error('Server returned non-JSON response');
        }
    })
    .then(({ status, data }) => {
        if (data.success) {
            if (typeof showToast === 'function') {
                showToast(data.message, 'success');
            }
            setTimeout(() => {
                window.location.replace(data.redirect);
            }, 500);
        } else {
            if (typeof showToast === 'function') {
                showToast(data.message || 'Failed to impersonate user.', 'error');
            }
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalHtml;
                submitBtn.classList.remove('opacity-70');
            }
        }
    })
    .catch(error => {
        console.error('Impersonation error:', error);
        if (typeof showToast === 'function') {
            showToast('An error occurred. Please try again.', 'error');
        }
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHtml;
            submitBtn.classList.remove('opacity-70');
        }
    });
}