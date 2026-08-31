# apps/tickets/asset_name_matching.py
"""Shared exact-match name lookup for linking a free-text "assigned to"
name (from an inventory import row, or a previously unresolved hint) to a
real User account. Deliberately exact-only, same posture as the
department/location/category import resolvers in views.py — fuzzy matching
here is exactly how 'Account' silently became a duplicate of 'Accounting'
in a different part of the same import.

Matches in both name orders (first+last AND last+first) because the
system's own first_name/last_name split and an imported/handwritten name
don't always agree on which is which."""
from django.db.models import Q, Value
from django.db.models.functions import Concat

from apps.accounts.models import User


def match_users_by_name(name):
    """Users whose "first last" or "last first" exactly matches `name`
    (case-insensitive). Returns a queryset — 0 results means no match, 2+
    means ambiguous; callers should treat both as "don't guess"."""
    name = (name or '').strip()
    if not name:
        return User.objects.none()
    return User.objects.annotate(
        full_name=Concat('first_name', Value(' '), 'last_name'),
        swapped_name=Concat('last_name', Value(' '), 'first_name'),
    ).filter(Q(full_name__iexact=name) | Q(swapped_name__iexact=name))
