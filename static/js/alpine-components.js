// static/js/alpine-components.js

document.addEventListener('alpine:init', () => {

    // ================================================================
    // 1. NAVBAR COMPONENT - Notification Bell + Role Switcher
    // ================================================================
    Alpine.data('navbarComponents', () => ({
        notificationOpen: false,
        roleDropdownOpen: false,
        activeRoleName: '',
        
        init() {
            this.activeRoleName = document.body.dataset.activeRole || '';
        },
        
        toggleNotifications() {
            this.notificationOpen = !this.notificationOpen;
            if (this.notificationOpen) {
                this.loadNotifications();
            }
        },
        
        loadNotifications() {
            const url = window.notificationsUrl || '/notifications/list/';
            htmx.ajax('GET', url, {
                target: '#notificationDropdownContent',
                swap: 'innerHTML'
            });
        },
        
        markReadAndGo(url, notificationId) {
            fetch(`/notifications/mark-read/${notificationId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            }).then(() => {
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
    }));

    // ================================================================
    // 2. THEME TOGGLE COMPONENT
    // ================================================================
    Alpine.data('themeToggle', () => ({
        theme: localStorage.getItem('theme') || 'light',
        
        init() {
            this.applyTheme(this.theme);
            this.$watch('theme', (value) => this.applyTheme(value));
        },
        
        setTheme(value) {
            this.theme = value;
        },
        
        applyTheme(theme) {
            const isDark = theme === 'dark';
            
            // Update HTML class
            document.documentElement.classList.toggle('dark', isDark);
            
            // Update CSS variables
            const colors = {
                light: {
                    '--color-background': '#f3f4f6',
                    '--color-surface': '#ffffff',
                    '--color-border': '#e5e7eb',
                    '--color-text-primary': '#111827',
                    '--color-text-secondary': '#6b7280',
                },
                dark: {
                    '--color-background': '#111827',
                    '--color-surface': '#1f2937',
                    '--color-border': '#374151',
                    '--color-text-primary': '#f9fafb',
                    '--color-text-secondary': '#9ca3af',
                }
            };
            
            const vars = colors[theme];
            if (vars) {
                Object.entries(vars).forEach(([key, value]) => {
                    document.documentElement.style.setProperty(key, value);
                });
            }
            
            localStorage.setItem('theme', theme);
            
            // Update radio buttons
            document.querySelectorAll('input[name="theme"]').forEach(el => {
                el.checked = (el.value === theme);
            });
            
            // Update label active states
            document.querySelectorAll('.theme-radio').forEach(el => {
                el.classList.toggle('active', el.querySelector('input')?.value === theme);
            });
        }
    }));

    // ================================================================
    // 3. SLIDEOVER COMPONENT
    // ================================================================
    Alpine.data('slideover', () => ({
        isOpen: false,
        content: '',
        
        init() {
            // Make globally accessible
            window.openSlideover = (content) => {
                this.open(content);
            };
            window.closeSlideover = () => {
                this.close();
            };
        },
        
        open(content = '') {
            this.isOpen = true;
            this.content = content;
            document.body.style.overflow = 'hidden';
            if (content) {
                document.getElementById('slideoverContent').innerHTML = content;
            }
        },
        
        close() {
            this.isOpen = false;
            document.body.style.overflow = '';
            setTimeout(() => {
                document.getElementById('slideoverContent').innerHTML = '';
                this.content = '';
            }, 300);
        }
    }));

    // ================================================================
    // 4. CONFIRMATION MODAL COMPONENT
    // ================================================================
    Alpine.data('modal', () => ({
        isOpen: false,
        title: 'Confirm Action',
        message: 'Are you sure you want to perform this action?',
        confirmCallback: null,
        
        init() {
            window.openConfirmationModal = (title, message, callback) => {
                this.open(title, message, callback);
            };
            window.closeConfirmationModal = () => {
                this.close();
            };
            window.confirmModal = this;
        },
        
        open(title = 'Confirm Action', message = 'Are you sure you want to perform this action?', callback = null) {
            this.title = title;
            this.message = message;
            this.confirmCallback = callback;
            this.isOpen = true;
            document.body.style.overflow = 'hidden';
        },
        
        close() {
            this.isOpen = false;
            document.body.style.overflow = '';
            this.confirmCallback = null;
        },
        
        confirm() {
            if (this.confirmCallback && typeof this.confirmCallback === 'function') {
                this.confirmCallback();
            }
            this.close();
        }
    }));

    // ================================================================
    // 5. TOAST MANAGER COMPONENT (FIXED - single definition)
    // ================================================================
    Alpine.data('toastManager', () => ({
        toasts: [],
        nextId: 0,
        
        init() {
            // Expose showToast globally for vanilla JS calls
            window.showToast = (message, type = 'info', duration = 5000) => {
                this.addToast(message, type, duration);
            };
            window.removeToast = (id) => {
                this.removeToast(id);
            };
            
            // Process Django messages after DOM is ready
            setTimeout(() => {
                this.processDjangoMessages();
            }, 100);
        },
        
        addToast(message, type = 'info', duration = 5000) {
            const icons = {
                success: '<svg class="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
                error: '<svg class="h-5 w-5 text-error" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
                warning: '<svg class="h-5 w-5 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
                info: '<svg class="h-5 w-5 text-info" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
            };
            
            const id = ++this.nextId;
            this.toasts.push({
                id: id,
                message: message,
                type: type,
                icon: icons[type] || icons.info,
                visible: true,
                duration: duration
            });
            
            if (duration > 0) {
                setTimeout(() => {
                    this.removeToast(id);
                }, duration);
            }
            
            return id;
        },
        
        removeToast(id) {
            const toast = this.toasts.find(t => t.id === id);
            if (toast) {
                toast.visible = false;
                setTimeout(() => {
                    this.toasts = this.toasts.filter(t => t.id !== id);
                }, 300);
            }
        },
        
        processDjangoMessages() {
            const messagesData = document.getElementById('django-messages-data');
            if (messagesData) {
                try {
                    const messages = JSON.parse(messagesData.dataset.messages);
                    if (messages && messages.length > 0) {
                        messages.forEach((msg) => {
                            let type = 'info';
                            if (msg.tags && msg.tags.includes('success')) type = 'success';
                            else if (msg.tags && msg.tags.includes('error')) type = 'error';
                            else if (msg.tags && msg.tags.includes('warning')) type = 'warning';
                            this.addToast(msg.text, type, 5000);
                        });
                    }
                } catch (e) {
                    console.error('Failed to parse messages:', e);
                }
            }
        }
    }));

    // ================================================================
    // 6. SIDEBAR ACCORDION COMPONENT (FIXED)
    // ================================================================
    Alpine.data('sidebarAccordion', () => ({
        activeSection: null,
        dashboardClicked: false,
        
        init() {
            this.dashboardClicked = localStorage.getItem('dashboard_clicked') === 'true';
            this.restoreSections();
            
            const dashboardLink = document.getElementById('dashboardLink');
            if (dashboardLink) {
                dashboardLink.addEventListener('click', () => {
                    this.collapseAll();
                    localStorage.setItem('dashboard_clicked', 'true');
                });
            }
        },
        
        toggleSection(sectionId) {
            if (this.dashboardClicked) {
                this.dashboardClicked = false;
                localStorage.removeItem('dashboard_clicked');
            }
            
            if (this.activeSection === sectionId) {
                this.activeSection = null;
                localStorage.setItem(`sidebar_section_${sectionId}`, 'collapsed');
            } else {
                this.activeSection = sectionId;
                localStorage.setItem(`sidebar_section_${sectionId}`, 'expanded');
            }
            
            // Update DOM after state change
            this.$nextTick(() => {
                this.updateSectionVisibility(sectionId);
            });
        },
        
        isSectionOpen(sectionId) {
            return this.activeSection === sectionId;
        },
        
        collapseAll() {
            this.activeSection = null;
            // Close all sections in DOM
            document.querySelectorAll('.section-content').forEach(el => {
                el.classList.add('hidden');
                el.style.maxHeight = '0';
                el.style.opacity = '0';
                el.style.overflow = 'hidden';
            });
            document.querySelectorAll('.section-chevron').forEach(el => {
                el.style.transform = 'rotate(-90deg)';
            });
        },
        
        restoreSections() {
            const sections = document.querySelectorAll('[data-section]');
            let hasExpanded = false;
            
            sections.forEach(el => {
                const sectionId = el.dataset.section;
                const content = document.getElementById(sectionId);
                const chevron = el.querySelector('.section-chevron');
                const savedState = localStorage.getItem(`sidebar_section_${sectionId}`);
                
                if (content) {
                    if (savedState === 'expanded' && !this.dashboardClicked) {
                        // Open the section
                        content.classList.remove('hidden');
                        content.style.maxHeight = content.scrollHeight + 'px';
                        content.style.opacity = '1';
                        content.style.overflow = '';
                        if (chevron) chevron.style.transform = 'rotate(0deg)';
                        this.activeSection = sectionId;
                        hasExpanded = true;
                    } else {
                        // Close the section
                        content.classList.add('hidden');
                        content.style.maxHeight = '0';
                        content.style.opacity = '0';
                        content.style.overflow = 'hidden';
                        if (chevron) chevron.style.transform = 'rotate(-90deg)';
                    }
                }
            });
            
            // If no section was expanded and there are sections, expand the first one
            if (!hasExpanded && sections.length > 0) {
                const firstSection = sections[0];
                const sectionId = firstSection.dataset.section;
                const content = document.getElementById(sectionId);
                const chevron = firstSection.querySelector('.section-chevron');
                if (content) {
                    this.activeSection = sectionId;
                    content.classList.remove('hidden');
                    content.style.maxHeight = content.scrollHeight + 'px';
                    content.style.opacity = '1';
                    content.style.overflow = '';
                    if (chevron) chevron.style.transform = 'rotate(0deg)';
                    localStorage.setItem(`sidebar_section_${sectionId}`, 'expanded');
                }
            }
        },
        
        updateSectionVisibility(sectionId) {
            const content = document.getElementById(sectionId);
            const toggle = document.querySelector(`[data-section="${sectionId}"]`);
            const chevron = toggle?.querySelector('.section-chevron');
            
            if (!content) return;
            
            if (this.activeSection === sectionId) {
                // Expand
                content.classList.remove('hidden');
                content.style.maxHeight = content.scrollHeight + 'px';
                content.style.opacity = '1';
                content.style.overflow = '';
                if (chevron) chevron.style.transform = 'rotate(0deg)';
            } else {
                // Collapse with animation
                content.style.maxHeight = content.scrollHeight + 'px';
                // Force reflow
                content.offsetHeight;
                content.style.maxHeight = '0';
                content.style.opacity = '0';
                content.style.overflow = 'hidden';
                setTimeout(() => {
                    content.classList.add('hidden');
                }, 300);
                if (chevron) chevron.style.transform = 'rotate(-90deg)';
            }
        }
    }));

    // ================================================================
    // 7. BULK ACTIONS COMPONENT
    // ================================================================
    Alpine.data('bulkActions', () => ({
        selected: [],
        source: 'unassigned',
        
        init() {
            this.source = window.bulkSource || 'unassigned';
            this.updateSelected();
        },
        
        updateSelected() {
            this.selected = Array.from(document.querySelectorAll('.ticket-checkbox:checked'))
                .map(cb => cb.value);
            this.updateUI();
        },
        
        toggleAll(checked) {
            document.querySelectorAll('.ticket-checkbox').forEach(cb => {
                cb.checked = checked;
            });
            this.updateSelected();
        },
        
        clear() {
            document.querySelectorAll('.ticket-checkbox').forEach(cb => {
                cb.checked = false;
            });
            this.updateSelected();
        },
        
        updateUI() {
            const count = this.selected.length;
            const bar = document.getElementById('bulkActionBar');
            const selectedCount = document.getElementById('selectedCount');
            const selectAll = document.getElementById('selectAll');
            
            if (bar) {
                if (count === 0) {
                    bar.classList.add('hidden');
                    bar.classList.remove('flex');
                } else {
                    bar.classList.remove('hidden');
                    bar.classList.add('flex');
                }
            }
            
            if (selectedCount) {
                selectedCount.innerText = count;
            }
            
            if (selectAll) {
                const total = document.querySelectorAll('.ticket-checkbox').length;
                selectAll.checked = (count === total && count > 0);
            }
        },
        
        submit(action, value = '') {
            if (this.selected.length === 0) return;
            
            fetch(window.bulkActionUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
                },
                body: new URLSearchParams({
                    'ticket_ids': this.selected.join(','),
                    'action': action,
                    'value': value,
                    'source': this.source,
                })
            }).then(response => response.text())
              .then(html => {
                  document.getElementById('ticketTable').innerHTML = html;
                  this.clear();
              });
        }
    }));

    // ================================================================
    // 8. KEYBOARD SHORTCUTS COMPONENT
    // ================================================================
    Alpine.data('keyboard', () => ({
        init() {
            document.addEventListener('keydown', this.handleKeydown.bind(this));
        },
        
        handleKeydown(e) {
            const target = e.target;
            
            if (target.tagName === 'INPUT' || 
                target.tagName === 'TEXTAREA' || 
                target.isContentEditable) {
                return;
            }
            
            if (e.key === 'Escape') {
                this.handleEscape();
                return;
            }
            
            if ((e.key === 'j' || e.key === 'k') && document.querySelector('.ticket-checkbox')) {
                e.preventDefault();
                this.navigateTickets(e.key);
                return;
            }
            
            if (e.key === 'Enter' && document.querySelector('.ticket-checkbox')) {
                const highlighted = document.querySelector('.highlighted-row');
                if (highlighted) {
                    e.preventDefault();
                    const viewLink = highlighted.querySelector('a[href*="conversation"], a[href*="slideover"]');
                    if (viewLink) {
                        if (viewLink.getAttribute('hx-get')) {
                            viewLink.click();
                        } else {
                            window.location.href = viewLink.href;
                        }
                    }
                }
            }
        },
        
        handleEscape() {
            if (typeof closeSlideover === 'function') closeSlideover();
            this.closeDetailsPanel();
            this.closeStatusMenu();
        },
        
        closeDetailsPanel() {
            const panel = document.getElementById('detailsPanel');
            if (panel && typeof toggleDetailsPanel === 'function') {
                if (!panel.classList.contains('hidden') && !panel.classList.contains('w-0')) {
                    toggleDetailsPanel();
                }
            }
        },
        
        closeStatusMenu() {
            const menu = document.getElementById('statusMenu');
            const chevron = document.getElementById('statusChevron');
            if (menu && !menu.classList.contains('hidden')) {
                menu.classList.add('hidden');
                if (chevron) chevron.classList.remove('rotate-180');
            }
        },
        
        navigateTickets(key) {
            const rows = Array.from(document.querySelectorAll('tr.group'));
            if (rows.length === 0) return;
            
            let currentIdx = rows.findIndex(r => r.classList.contains('highlighted-row'));
            if (currentIdx === -1) currentIdx = 0;
            
            rows.forEach(r => r.classList.remove('highlighted-row'));
            
            if (key === 'j') {
                currentIdx = (currentIdx + 1) % rows.length;
            } else {
                currentIdx = (currentIdx - 1 + rows.length) % rows.length;
            }
            
            rows[currentIdx].classList.add('highlighted-row');
            rows[currentIdx].scrollIntoView({block: 'nearest', behavior: 'smooth'});
        }
    }));

    // ================================================================
    // 9. CONVERSATION PAGE COMPONENTS
    // ================================================================
    Alpine.data('conversation', () => ({
        statusMenuOpen: false,
        detailsOpen: false,
        
        toggleStatusMenu() {
            this.statusMenuOpen = !this.statusMenuOpen;
        },
        
        toggleDetails() {
            this.detailsOpen = !this.detailsOpen;
            const panel = document.getElementById('detailsPanel');
            if (panel) {
                if (window.innerWidth < 640) {
                    panel.classList.toggle('w-0');
                    panel.classList.toggle('w-full');
                } else {
                    panel.classList.toggle('w-0');
                    panel.classList.toggle('w-80');
                    panel.classList.toggle('w-96');
                }
            }
        },
        
        setActiveTab(mode) {
            const publicSpan = document.getElementById('tabPublic');
            const internalSpan = document.getElementById('tabInternal');
            if (!publicSpan || !internalSpan) return;
            
            if (mode === 'public') {
                publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
                internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
                const publicRadio = document.querySelector('input[value="PUBLIC"]');
                if (publicRadio) publicRadio.checked = true;
            } else {
                internalSpan.className = 'px-3 py-1 rounded-full inline-block bg-primary text-white border border-primary';
                publicSpan.className = 'px-3 py-1 rounded-full inline-block bg-background text-text-secondary border border-border';
                const internalRadio = document.querySelector('input[value="INTERNAL"]');
                if (internalRadio) internalRadio.checked = true;
            }
        },
        
        insertMacro(body, visibility) {
            const editor = document.getElementById('commentEditor');
            if (editor) {
                editor.innerHTML = body;
                this.setActiveTab(visibility.toLowerCase());
                const radios = document.getElementsByName('visibility');
                for (let radio of radios) {
                    if (radio.value === visibility) radio.checked = true;
                }
                this.statusMenuOpen = false;
            }
        },
        
        scrollToBottom() {
            const el = document.getElementById('commentTimeline');
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }
    }));

    // ================================================================
    // 10. ADMIN USER MANAGEMENT COMPONENTS
    // ================================================================
    Alpine.data('adminUsers', () => ({
        createModalOpen: false,
        editModalOpen: false,
        passwordModalOpen: false,
        impersonateModalOpen: false,
        userId: null,
        
        openCreateModal() {
            this.createModalOpen = true;
        },
        
        closeCreateModal() {
            this.createModalOpen = false;
            document.getElementById('createUserForm')?.reset();
        },
        
        openEditModal(userId) {
            const row = document.querySelector(`tr[data-user-id="${userId}"]`);
            if (!row) return;
            
            this.userId = userId;
            document.getElementById('editUserId').value = userId;
            document.getElementById('editEmail').value = row.dataset.email;
            document.getElementById('editFirstName').value = row.dataset.firstName;
            document.getElementById('editLastName').value = row.dataset.lastName;
            document.getElementById('editRole').value = row.dataset.role;
            document.getElementById('editDepartment').value = row.dataset.department;
            document.getElementById('editIsActive').checked = row.dataset.isActive === 'true';
            
            const roleCheckboxes = document.querySelectorAll('#editRolesCheckboxes input[name="selected_roles"]');
            roleCheckboxes.forEach(checkbox => { checkbox.checked = false; });
            const assignedRoles = row.dataset.assignedRoles ? row.dataset.assignedRoles.split(',') : [];
            roleCheckboxes.forEach(checkbox => {
                checkbox.checked = assignedRoles.includes(checkbox.value);
            });
            
            const activeRoleValue = row.dataset.activeRole || row.dataset.role || '';
            const editActiveRole = document.getElementById('editActiveRole');
            if (editActiveRole) {
                editActiveRole.value = activeRoleValue;
            }
            
            this.editModalOpen = true;
        },
        
        closeEditModal() {
            this.editModalOpen = false;
        },
        
        openPasswordModal(userId) {
            const row = document.querySelector(`tr[data-user-id="${userId}"]`);
            if (!row) return;
            
            this.userId = userId;
            document.getElementById('passwordUserId').value = userId;
            
            const firstName = row.dataset.firstName || '';
            const lastName = row.dataset.lastName || '';
            const fullName = (firstName + ' ' + lastName).trim() || row.dataset.email || '';
            const role = row.dataset.role || '';
            const department = row.dataset.department || '';
            
            document.getElementById('passwordUserName').innerText = fullName;
            document.getElementById('passwordUserDetails').innerText = 
                'Role: ' + role + ' | Department: ' + (department || 'None');
            
            this.passwordModalOpen = true;
        },
        
        closePasswordModal() {
            this.passwordModalOpen = false;
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
        },
        
        togglePasswordVisibility(inputId, eyeId, eyeOffId) {
            const input = document.getElementById(inputId);
            const eye = document.getElementById(eyeId);
            const eyeOff = document.getElementById(eyeOffId);
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
        },
        
        openImpersonateModal(userId, userName) {
            this.userId = userId;
            window.impersonateUserId = userId;
            window.impersonateUserName = userName;
            
            htmx.ajax('GET', `/accounts/impersonate/modal/?user_id=${userId}&user_name=${encodeURIComponent(userName)}`, {
                target: '#impersonateModalContainer',
                swap: 'innerHTML',
                onAfterSwap: () => {
                    const userIdInput = document.getElementById('impersonateUserId');
                    if (userIdInput) {
                        userIdInput.value = userId;
                    }
                    const nameElement = document.getElementById('impersonateUserName');
                    if (nameElement && userName) {
                        nameElement.textContent = userName;
                    }
                    this.initImpersonateReasonHandler();
                }
            });
            
            this.impersonateModalOpen = true;
        },
        
        closeImpersonateModal() {
            this.impersonateModalOpen = false;
            document.getElementById('impersonateModalContainer').innerHTML = '';
        },
        
        initImpersonateReasonHandler() {
            const reasonSelect = document.getElementById('impersonateReason');
            const otherContainer = document.getElementById('otherReasonContainer');
            
            if (reasonSelect) {
                reasonSelect.removeEventListener('change', this.handleReasonChange);
                reasonSelect.addEventListener('change', this.handleReasonChange.bind(this));
            }
        },
        
        handleReasonChange() {
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
        },
        
        handleImpersonateSubmit(e) {
            e.preventDefault();
            
            const userId = document.getElementById('impersonateUserId')?.value || window.impersonateUserId;
            const reasonSelect = document.getElementById('impersonateReason');
            let reason = reasonSelect?.value || '';
            
            if (!userId) {
                if (typeof window.showToast === 'function') {
                    window.showToast('User ID not found. Please try again.', 'error');
                }
                return;
            }
            
            if (reason === 'Other') {
                reason = document.getElementById('otherReason')?.value?.trim() || '';
                if (!reason) {
                    if (typeof window.showToast === 'function') {
                        window.showToast('Please specify the reason for impersonation.', 'error');
                    }
                    return;
                }
            }
            
            if (!reason) {
                if (typeof window.showToast === 'function') {
                    window.showToast('Please select a reason for impersonation.', 'error');
                }
                return;
            }
            
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
            if (!csrfToken) {
                if (typeof window.showToast === 'function') {
                    window.showToast('Security token missing. Please refresh the page.', 'error');
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
                    if (typeof window.showToast === 'function') {
                        window.showToast(data.message, 'success');
                    }
                    setTimeout(() => {
                        window.location.replace(data.redirect);
                    }, 500);
                } else {
                    if (typeof window.showToast === 'function') {
                        window.showToast(data.message || 'Failed to impersonate user.', 'error');
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
                if (typeof window.showToast === 'function') {
                    window.showToast('An error occurred. Please try again.', 'error');
                }
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalHtml;
                    submitBtn.classList.remove('opacity-70');
                }
            });
        },
        
        refreshTable() {
            const q = document.getElementById('searchInput')?.value || '';
            const role = document.getElementById('roleFilter')?.value || '';
            const dept = document.getElementById('departmentFilter')?.value || '';
            const params = new URLSearchParams({ q, role, department: dept });
            const url = window.adminUsersUrl + '?' + params.toString();
            htmx.ajax('GET', url, { target: '#userTableContainer', swap: 'innerHTML' });
        }
    }));

    // ================================================================
    // 11. ASSET MANAGEMENT COMPONENTS
    // ================================================================
    Alpine.data('assetManagement', () => ({
        modalOpen: false,
        exportDropdownOpen: false,
        importModalOpen: false,
        assetId: null,
        
        init() {
            document.addEventListener('click', (event) => {
                const dropdown = document.getElementById('exportDropdown');
                const button = document.querySelector('[x-on\\:click="toggleExportDropdown"]');
                if (dropdown && button && !dropdown.contains(event.target) && !button.contains(event.target)) {
                    this.exportDropdownOpen = false;
                }
            });
        },
        
        openModal(url) {
            const overlay = document.getElementById('modalOverlay');
            const container = document.getElementById('modalContainer');
            
            if (!overlay || !container) return;
            
            container.innerHTML = '<div class="p-6 text-center text-text-secondary">Loading...</div>';
            overlay.classList.remove('hidden');
            this.modalOpen = true;
            
            htmx.ajax('GET', url, {
                target: '#modalContainer',
                swap: 'innerHTML',
                onError: () => {
                    container.innerHTML = '<div class="p-6 text-center text-error">Failed to load modal. Please try again.</div>';
                    if (typeof window.showToast === 'function') {
                        window.showToast('Failed to load modal.', 'error');
                    }
                }
            });
        },
        
        closeModal() {
            this.modalOpen = false;
            const overlay = document.getElementById('modalOverlay');
            const container = document.getElementById('modalContainer');
            if (overlay) overlay.classList.add('hidden');
            if (container) {
                setTimeout(() => {
                    container.innerHTML = '';
                }, 150);
            }
        },
        
        openScrapApproveModal(assetId) {
            this.assetId = assetId;
            const url = window.scrapApproveModalUrl?.replace('0', assetId);
            if (url) this.openModal(url);
        },
        
        openScrapRequestModal(assetId) {
            this.assetId = assetId;
            const url = window.scrapRequestModalUrl?.replace('0', assetId);
            if (url) this.openModal(url);
        },
        
        openAssetReassignModal(assetId) {
            this.assetId = assetId;
            const url = window.assetReassignModalUrl?.replace('0', assetId);
            if (url) this.openModal(url);
        },
        
        editAsset(assetId) {
            this.assetId = assetId;
            const url = window.editUrl?.replace('0', assetId);
            if (url) this.openModal(url);
        },
        
        toggleExportDropdown() {
            this.exportDropdownOpen = !this.exportDropdownOpen;
        },
        
        resetFilters(e) {
            if (e) e.preventDefault();
            const form = document.getElementById('assetFilters');
            if (!form) return;
            
            form.querySelectorAll('input, select').forEach(el => {
                if (el.tagName === 'INPUT') {
                    el.value = '';
                } else if (el.tagName === 'SELECT') {
                    el.selectedIndex = 0;
                }
            });
            
            if (window.assetsUrl) {
                htmx.ajax('GET', window.assetsUrl, {
                    target: '#assetTableContainer',
                    swap: 'innerHTML'
                });
            }
        }
    }));

    // ================================================================
    // 12. RICH TEXT EDITOR COMPONENT
    // ================================================================
    Alpine.data('editor', () => ({
        content: '',
        draftKey: null,
        
        init() {
            this.draftKey = this.$el.getAttribute('data-draft-key');
            if (this.draftKey) {
                const saved = localStorage.getItem(this.draftKey);
                if (saved) {
                    this.content = saved;
                    this.$el.innerHTML = saved;
                }
            }
            
            this.$el.addEventListener('input', () => {
                this.content = this.$el.innerHTML;
                if (this.draftKey) {
                    localStorage.setItem(this.draftKey, this.content);
                }
            });
            
            const form = this.$el.closest('form');
            if (form && this.draftKey) {
                form.addEventListener('htmx:afterRequest', () => {
                    localStorage.removeItem(this.draftKey);
                    this.content = '';
                    this.$el.innerHTML = '';
                });
            }
        },
        
        format(command, value = null) {
            this.$el.focus();
            document.execCommand(command, false, value);
        },
        
        getContent() {
            return this.$el.innerHTML;
        }
    }));

    // ================================================================
    // 13. FULFILLMENT MODAL COMPONENT
    // ================================================================
    Alpine.data('fulfillment', () => ({
        isOpen: false,
        ticketId: null,
        
        open(ticketId) {
            this.ticketId = ticketId;
            this.isOpen = true;
            document.body.style.overflow = 'hidden';
            
            const existing = document.getElementById('fulfillModal');
            if (existing) existing.remove();
            
            fetch(`/tickets/assets/fulfill-modal/${ticketId}/`)
                .then(response => response.text())
                .then(html => {
                    const wrapper = document.createElement('div');
                    wrapper.innerHTML = html;
                    document.body.appendChild(wrapper.firstElementChild);
                    
                    const modal = document.getElementById('fulfillModal');
                    if (modal && typeof htmx !== 'undefined') {
                        htmx.process(modal);
                    }
                    
                    if (modal) {
                        modal.addEventListener('click', (e) => {
                            if (e.target === this) {
                                this.close();
                            }
                        });
                    }
                })
                .catch(error => {
                    console.error('Error loading fulfill modal:', error);
                    document.body.style.overflow = '';
                    if (typeof window.showToast === 'function') {
                        window.showToast('Error loading fulfillment form.', 'error');
                    }
                    this.isOpen = false;
                });
        },
        
        close() {
            const modal = document.getElementById('fulfillModal');
            if (modal) modal.remove();
            document.body.style.overflow = '';
            this.isOpen = false;
            this.ticketId = null;
        }
    }));
});