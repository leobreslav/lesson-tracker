"""
Joining a school.

The only way in is an invitation an administrator wrote down in advance,
matched against the address the provider itself verified.
"""

from django.db import transaction
from django.utils import timezone

from .models import Invitation


def pending_for(email: str):
    """
    The unused invitation for this address, if there is one.

    Addresses are compared case-insensitively: an administrator types
    «Ivan.Petrov@school.ru», Google reports «ivan.petrov@school.ru», and the
    same person should walk in either way.
    """
    if not email:
        return None

    return (
        Invitation.objects.filter(email__iexact=email.strip(), accepted_at__isnull=True)
        .select_related("school")
        .order_by("created_at")
        .first()
    )


@transaction.atomic
def accept(user, invitation) -> bool:
    """
    Attach the user to the school and stamp the invitation.

    Someone who already belongs to a school is left alone: a second
    invitation must not silently move a teacher, with their whole schedule,
    into another building.
    """
    if user.school_id is not None:
        return False

    user.school = invitation.school
    user.is_school_admin = invitation.is_school_admin
    user.save(update_fields=["school", "is_school_admin"])

    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return True


def accept_for(user, verified_emails) -> bool:
    """
    Try every address the provider vouched for.

    The addresses come from the provider, never from a form: matching what a
    person typed about themselves would let anyone claim a colleague's
    invitation by writing their address in a profile field.
    """
    for email in verified_emails:
        invitation = pending_for(email)
        if invitation is not None and accept(user, invitation):
            return True
    return False
