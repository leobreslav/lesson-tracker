from allauth.account.signals import user_logged_in
from django.dispatch import receiver
from schools import services as school_services


@receiver(user_logged_in)
def join_invited_school(sender, request, user, sociallogin=None, **kwargs):
    """
    Attach a newly arrived teacher to the school that invited them.

    The match runs on the addresses Google marked as verified, not on
    anything the person typed about themselves: an invitation is an
    authorisation, and a self-declared address would let anyone claim
    somebody else's.

    It runs on every sign-in rather than on registration only: an
    administrator often writes the address down after the person has already
    tried to get in, and the second attempt should simply work.
    """
    if sociallogin is None:
        return

    verified = [
        address.email for address in sociallogin.email_addresses if address.verified
    ]
    school_services.accept_for(user, verified)


@receiver(user_logged_in)
def fill_name_from_google(sender, request, user, sociallogin=None, **kwargs):
    """
    Fills in the first and last name from Google when they are empty.

    allauth fills them itself when registering a new user, but an existing
    account (made by createsuperuser, or found by email) goes through no
    registration and the fields stay empty.

    Values already there are left alone: the person may have edited them in
    their profile, and signing in through Google must not overwrite that.
    """
    if sociallogin is None:
        return

    data = sociallogin.account.extra_data
    updated = []

    if not user.first_name and data.get("given_name"):
        user.first_name = data["given_name"][:150]
        updated.append("first_name")

    if not user.last_name and data.get("family_name"):
        user.last_name = data["family_name"][:150]
        updated.append("last_name")

    if updated:
        user.save(update_fields=updated)
