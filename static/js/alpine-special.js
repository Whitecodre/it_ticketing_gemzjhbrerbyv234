// static/js/alpine-special.js
// ================================================================
// ALPINE.JS COMPONENTS - For Special Pages Only
// ================================================================
// This file is ONLY loaded on pages that require Alpine.js:
// - Form Builder (form_builder/builder.html)
// - System Organogram (organogram/system.html)
// - Organogram Builder (organogram/builder.html)
//
// Do NOT load this file on the main dashboard.
// The main dashboard uses vanilla JS (global.js, etc.)
// ================================================================

document.addEventListener('alpine:init', () => {

    // ================================================================
    // ORGANOGRAM COMPONENTS (for system.html and builder.html)
    // ================================================================
    
    Alpine.data('orgTree', () => ({
        expandedNodes: [],
        init() {
            // Auto-expand first two levels
        }
    }));
    
    Alpine.data('orgNode', (nodeId, depth, hasChildren) => ({
        nodeId: nodeId,
        depth: depth,
        hasChildren: hasChildren,
        isExpanded: false,
        
        init() {
            // Auto-expand first two levels
            if (this.depth < 2) {
                this.isExpanded = true;
            }
        },
        
        toggleExpand(event, id) {
            event.stopPropagation();
            this.isExpanded = !this.isExpanded;
        }
    }));

    // ================================================================
    // ORG BUILDER COMPONENTS (for builder.html)
    // ================================================================
    
    Alpine.data('orgBuilder', () => ({
        structure: [],
        nextId: 0,
        
        init(initialData) {
            if (initialData && initialData.nodes) {
                this.structure = initialData.nodes;
                this.nextId = this.getMaxId() + 1;
            } else {
                this.structure = [];
                this.nextId = 1;
            }
        },
        
        getMaxId() {
            let maxId = 0;
            const traverse = (nodes) => {
                nodes.forEach(node => {
                    if (node.id && node.id > maxId) maxId = node.id;
                    if (node.children) traverse(node.children);
                });
            };
            traverse(this.structure);
            return maxId;
        },
        
        countNodes() {
            let total = 0;
            const traverse = (nodes) => {
                nodes.forEach(node => {
                    total += 1;
                    if (node.children) traverse(node.children);
                });
            };
            traverse(this.structure);
            return total;
        },
        
        addRoot() {
            this.structure.push({
                id: this.nextId++,
                label: 'New Department',
                position: 'Department Head',
                color: '#0D9488',
                children: []
            });
            this.autoSave();
        },
        
        addChild(parentIndex) {
            if (parentIndex === undefined) {
                if (this.structure.length > 0) {
                    this.addChildToPath([this.structure.length - 1]);
                } else {
                    this.addRoot();
                }
                return;
            }
            this.addChildToPath([parentIndex]);
        },
        
        addChildToNode(parentIndex, childIndex) {
            const parent = this.structure[parentIndex];
            if (!parent || !parent.children || !parent.children[childIndex]) return;
            const node = parent.children[childIndex];
            if (!node.children) node.children = [];
            node.children.push({
                id: this.nextId++,
                label: 'New Position',
                position: 'Position',
                color: '#8B5CF6',
                children: []
            });
            this.autoSave();
        },
        
        removeChild(parentIndex, childIndex) {
            const parent = this.structure[parentIndex];
            if (!parent || !parent.children) return;
            parent.children.splice(childIndex, 1);
            this.autoSave();
        },
        
        getNodeByPath(path) {
            let node = null;
            let nodes = this.structure;
            for (let index of path) {
                node = nodes?.[index];
                if (!node) return null;
                nodes = node.children || [];
            }
            return node;
        },
        
        addChildToPath(path) {
            const target = this.getNodeByPath(path);
            if (!target) return;
            if (!target.children) target.children = [];
            target.children.push({
                id: this.nextId++,
                label: 'New Position',
                position: 'Position',
                color: '#3B82F6',
                children: []
            });
            this.autoSave();
        },
        
        removeNodeAtPath(path) {
            const parentPath = path.slice(0, -1);
            const parent = parentPath.length ? this.getNodeByPath(parentPath) : null;
            const collection = parent ? parent.children : this.structure;
            if (!collection) return;
            collection.splice(path[path.length - 1], 1);
            this.autoSave();
        },
        
        autoSave() {
            clearTimeout(this._saveTimeout);
            this._saveTimeout = setTimeout(() => {
                this.saveStructure();
            }, 1000);
        },
        
        saveStructure() {
            const draftId = parseInt(document.getElementById('draftId')?.value || '0');
            if (!draftId) return;
            
            const data = {
                draft_id: draftId,
                structure: { nodes: this.structure }
            };
            
            fetch('/organogram/api/save-structure/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',
                },
                body: JSON.stringify(data),
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    // Update status
                }
            });
        }
    }));

});