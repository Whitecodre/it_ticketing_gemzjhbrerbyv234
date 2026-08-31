from urllib.parse import quote

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from .models import Asset, Ticket, TicketComment
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


@receiver(pre_save, sender=User)
def _capture_old_name_for_asset_resolve(sender, instance, **kwargs):
    """Stash the pre-save name so the post_save handler below can tell a real
    rename (which may newly match an unresolved import hint) apart from an
    unrelated profile save (department, role, etc.) that happens to touch the
    same row."""
    if not instance.pk:
        instance._old_full_name_for_resolve = ''
        return
    try:
        old = User.objects.only('first_name', 'last_name').get(pk=instance.pk)
        instance._old_full_name_for_resolve = f"{old.first_name} {old.last_name}".strip()
    except User.DoesNotExist:
        instance._old_full_name_for_resolve = ''


@receiver(post_save, sender=User)
def flag_assets_resolvable_for_new_user(sender, instance, created, **kwargs):
    """A newly created account, or an existing one renamed, may be the very
    person an earlier inventory import couldn't match — its raw "assigned to"
    text is preserved on Asset.unresolved_assignee_hint rather than discarded
    (see asset_import_commit). Auto-assigns every matching asset to the
    account (via the same release()+assign_to() pair asset_reassign uses, so
    checked_out_to/status/AssetCheckoutHistory stay in lockstep and the new
    holder gets assign_to()'s own "please confirm receipt" notification) and
    tells admins it happened, for visibility/audit — not for them to action.
    A match that's blocked (e.g. the asset is currently mobilized) is left
    alone and admins are told to handle it manually instead. Only fires when
    the name actually changed (new account, or a rename), not on unrelated
    profile edits, so it can't repeat-fire every time the account is saved."""
    full_name = f"{instance.first_name} {instance.last_name}".strip()
    old_full_name = getattr(instance, '_old_full_name_for_resolve', '')
    if not created and full_name == old_full_name:
        return
    swapped_name = f"{instance.last_name} {instance.first_name}".strip()
    if not full_name:
        return
    hints = list(Asset.objects.filter(
        Q(unresolved_assignee_hint__iexact=full_name) |
        Q(unresolved_assignee_hint__iexact=swapped_name)
    ).exclude(unresolved_assignee_hint=''))
    if not hints:
        return
    hint_text = hints[0].unresolved_assignee_hint

    admins = User.objects.filter(role__in=[User.Role.ADMIN, User.Role.SUPERADMIN], is_active=True)
    # release()/assign_to() require a real actor for AssetCheckoutHistory
    # (checked_out_by is NOT NULL) — there's no request.user here since this
    # runs off a plain model save, so fall back to a system-ish actor the
    # same way apps/tickets/management/commands/backfill_asset_assignments.py
    # does for its own actor-less auto-assignment.
    system_actor = User.objects.filter(is_superuser=True, is_active=True).first() or admins.first()

    assigned, blocked = [], []
    for asset in hints:
        if not system_actor or not asset.can_reassign:
            blocked.append(asset)
            continue
        try:
            with transaction.atomic():
                asset.release(actor=system_actor, return_reason=Asset.ReturnReason.OTHER,
                               return_comment=f'Auto-linked to {instance.get_full_name()} on account match')
                asset.assign_to(instance, actor=system_actor,
                                 notes=f'Auto-assigned: import hint "{hint_text}" matched {instance.get_full_name()}')
            assigned.append(asset)
        except ValueError:
            blocked.append(asset)

    assets_url = reverse('tickets:assets') + f'?filter_q={quote(hint_text)}&filter_group_by_owner=0'
    for admin in admins:
        if assigned:
            Notification.objects.create(
                recipient=admin, role=role_of(admin),
                message=f'{instance.get_full_name()} matched {len(assigned)} imported asset(s) that listed '
                        f'"{hint_text}" as their holder — auto-assigned to them.',
                url=assets_url,
            )
        if blocked:
            Notification.objects.create(
                recipient=admin, role=role_of(admin),
                message=f'{instance.get_full_name()} matches {len(blocked)} imported asset(s) listed '
                        f'"{hint_text}" as their holder, but they could not be auto-assigned — review manually.',
                url=assets_url,
            )