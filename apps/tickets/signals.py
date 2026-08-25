from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from .models import Ticket, TicketComment
from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import role_of

@receiver(post_save, sender=Ticket)
def create_ticket_notification(sender, instance, created, **kwargs):
    if created:
        # Notify the requester (always)
        Notification.objects.create(
            recipient=instance.requester,
            role=role_of(instance.requester),
            message=f"Ticket {instance.number} created successfully.",
            url=reverse('tickets:detail', args=[instance.pk])
        )
        
        # ONLY notify agents about unassigned tickets if it's an INCIDENT
        # Service requests go to manager review instead
        if instance.type == Ticket.Type.INCIDENT:
            agents = User.objects.filter(role__in=[User.Role.AGENT, User.Role.TEAM_LEAD])
            for agent in agents:
                Notification.objects.create(
                    recipient=agent,
                    role=role_of(agent),
                    message=f"New unassigned ticket {instance.number}: {instance.title}",
                    url=reverse('tickets:detail', args=[instance.pk])
                )
        # For SERVICE_REQUESTS, notifications are sent in create_ticket view to Team Leads
        # No additional notification needed here

@receiver(post_save, sender=TicketComment)
def create_comment_notification(sender, instance, created, **kwargs):
    if created and instance.visibility == TicketComment.Visibility.PUBLIC:
        # Notify the requester if someone else replied
        if instance.author != instance.ticket.requester:
            Notification.objects.create(
                recipient=instance.ticket.requester,
                role=role_of(instance.ticket.requester),
                message=f"New reply on ticket {instance.ticket.number}.",
                url=reverse('tickets:detail', args=[instance.ticket.pk])
            )
        # Notify the assigned agent (if any) when the requester posts a reply
        if instance.author == instance.ticket.requester and instance.ticket.assigned_to:
            Notification.objects.create(
                recipient=instance.ticket.assigned_to,
                role=role_of(instance.ticket.assigned_to),
                message=f"{instance.ticket.requester.get_full_name()} replied to ticket {instance.ticket.number}.",
                url=reverse('tickets:detail', args=[instance.ticket.pk])
            )

@receiver(post_save, sender=Ticket)
def handle_ticket_fulfillment_notification(sender, instance, created, **kwargs):
    """Send notifications when a ticket is fulfilled."""
    if created:
        return
    
    # Check if this ticket was just fulfilled
    if instance.status == Ticket.Status.APPROVED and instance.fulfilled_at:
        # Check if it was newly fulfilled (using a flag or tracking)
        try:
            old_instance = Ticket.objects.get(pk=instance.pk)
            if old_instance.status != Ticket.Status.APPROVED and old_instance.fulfilled_at is None:
                # This is a new fulfillment
                Notification.objects.create(
                    recipient=instance.requester,
                    role=role_of(instance.requester),
                    message=f'Your asset request {instance.number} has been fulfilled. Asset assigned to you.',
                    url=reverse('tickets:detail', args=[instance.pk])
                )
        except Ticket.DoesNotExist:
            pass