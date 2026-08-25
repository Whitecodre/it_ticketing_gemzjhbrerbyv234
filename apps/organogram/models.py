# apps/organogram/models.py
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


# ================================================================
# SYSTEM ORGANOGRAM (Auto-generated from Users)
# ================================================================

class SystemOrgConfig(models.Model):
    """Configuration for system organogram display."""

    department = models.CharField(
        max_length=30,
        choices=User.DEPARTMENT_CHOICES,
        unique=True
    )
    color = models.CharField(max_length=7, default='#64748B')
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        verbose_name = 'System Org Config'
        verbose_name_plural = 'System Org Configs'

    def __str__(self):
        return f"{self.get_department_display()} - {self.color}"
