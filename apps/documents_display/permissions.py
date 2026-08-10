from rest_framework import permissions


class CanEditDocument(permissions.BasePermission):
    """Check if user can edit a document"""
    
    def has_object_permission(self, request, view, obj):
        return obj.is_editable_by(request.user)


class CanViewDocument(permissions.BasePermission):
    """Check if user can view a document"""
    
    def has_object_permission(self, request, view, obj):
        if obj.is_deleted:
            return False
        return True