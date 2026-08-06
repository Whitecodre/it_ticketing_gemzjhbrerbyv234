# apps/maintenance/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import MaintenanceSchedule, MaintenanceActivityLog


@receiver(post_save, sender=MaintenanceSchedule)
def log_assignment_change(sender, instance, created, **kwargs):
    """Log when assigned_to changes."""
    if created:
        return
    
    # Check if this is an update (not creation)
    if instance.pk:
        try:
            old = MaintenanceSchedule.objects.get(pk=instance.pk)
            if old.assigned_to != instance.assigned_to:
                # Assignment changed
                if instance.assigned_to:
                    MaintenanceActivityLog.objects.create(
                        schedule=instance,
                        action=MaintenanceActivityLog.Action.ASSIGNED,
                        details={
                            'from': old.assigned_to.email if old.assigned_to else None,
                            'to': instance.assigned_to.email
                        }
                    )
        except MaintenanceSchedule.DoesNotExist:
            pass