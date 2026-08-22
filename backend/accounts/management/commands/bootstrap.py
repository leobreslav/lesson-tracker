"""
Bring an empty or incomplete database up to a working state.

This runs on the live database at every container start, so it obeys one
rule: it only ever adds what is missing. Nothing is deleted, nothing existing
is rewritten, and running it ten times leaves exactly what running it once
did.

Adding a step later — a reference list, default settings, a role — means
writing one function and putting it in STEPS. A step reports what it did in
its own words and never raises for a condition an operator can fix; a
missing environment variable is a warning, not a crash, because a container
that refuses to start is worse than one missing an optional account.
"""

import os
import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

# what a step tells the operator: whether the database changed, and why
CHANGED = "changed"
ALREADY = "already"
SKIPPED = "skipped"


def report(state, message):
    return state, message


def ensure_superuser():
    """
    Create the first superuser, if the installation has none.

    Only when there is none at all: once somebody can reach /admin/, this
    step must never touch accounts again — a deploy is not the place to
    change who has the keys.

    If the address already belongs to an ordinary account, that account is
    promoted rather than duplicated. That is the usual case in practice: the
    person signs in through Google first and only then gets named as the
    superuser.
    """
    if User.objects.filter(is_superuser=True).exists():
        holder = User.objects.filter(is_superuser=True).first()
        return report(ALREADY, f"суперпользователь уже есть: {holder.email}")

    email = (os.environ.get("BOOTSTRAP_SUPERUSER_EMAIL") or "").strip().lower()
    password = os.environ.get("BOOTSTRAP_SUPERUSER_PASSWORD") or ""

    if not email or not password:
        return report(
            SKIPPED,
            "суперпользователя нет, но BOOTSTRAP_SUPERUSER_EMAIL и "
            "BOOTSTRAP_SUPERUSER_PASSWORD не заданы — пропускаю",
        )

    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None:
        existing.is_superuser = True
        existing.is_staff = True
        existing.set_password(password)
        existing.save(update_fields=["is_superuser", "is_staff", "password"])
        return report(CHANGED, f"существующий {existing.email} стал суперпользователем")

    User.objects.create_superuser(email=email, password=password)
    return report(CHANGED, f"создан суперпользователь {email}")


def ensure_named_superusers():
    """
    Keep every account named in BOOTSTRAP_SUPERUSERS a superuser, at every start.

    `ensure_superuser` gives up as soon as anybody is a superuser, and that
    is right for a live installation: a deploy is not the place to decide
    who holds the keys. It is wrong for a stand whose database is thrown
    away and seeded again — and there it has a trap. Seeding creates its own
    `developer@example.com`, so the very first seed closes that door: the
    live person is never promoted again, however many variables are set.
    Twice we answered this with a flag on the seeding command, and twice it
    was forgotten by the next reseed.

    So this step answers a different question. Not "who becomes the first
    superuser" but "who is a superuser on this contour, always" — a standing
    declaration, re-applied on every container start. Naming an address in
    the env file is not an escalation: whoever can edit that file owns the
    machine already.

    Two limits keep it from becoming the thing `ensure_superuser` refuses to
    be. It only ever grants: an address dropped from the list leaves the
    account exactly as it is, because demoting people during a deploy is how
    a deploy locks its owner out. And it never touches a password — an
    account created here signs in through Google like everyone else, and
    /admin/ stays the business of `BOOTSTRAP_SUPERUSER_*`.

    Empty on production, and that is the configuration rather than an
    oversight: there the superuser is made once and changed by hand.
    """
    names = [
        part.lower()
        for part in re.split(r"[,\s]+", os.environ.get("BOOTSTRAP_SUPERUSERS") or "")
        if part
    ]
    # An empty list is a legitimate setting, not a half-configured one, so it
    # reports neutrally. A warning printed at every production start is a
    # warning people learn to skip, and then it is missed where it matters.
    if not names:
        return report(ALREADY, "BOOTSTRAP_SUPERUSERS пуст — список прав не трогаю")

    created, promoted, already = [], [], []

    for email in names:
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            created.append(User.objects.create_superuser(email=email).email)
        elif user.is_superuser and user.is_staff:
            already.append(user.email)
        else:
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=["is_superuser", "is_staff"])
            promoted.append(user.email)

    said = []
    if created:
        said.append(f"создан суперпользователь {', '.join(created)}")
    if promoted:
        said.append(f"повышен до суперпользователя {', '.join(promoted)}")
    if already:
        said.append(f"уже суперпользователь: {', '.join(already)}")

    return report(CHANGED if created or promoted else ALREADY, "; ".join(said))


def ensure_verified_emails():
    """
    Give every staff account a verified EmailAddress row.

    Without one, allauth's email authentication calls `wipe_password` on the
    first Google sign-in and the account loses its /admin/ password. We have
    walked into that once already.

    `UserManager` does this for accounts it creates, so this step is normally
    a no-op — it exists for accounts made another way, and for the ones that
    predate that manager.
    """
    fixed = []

    for user in User.objects.filter(is_staff=True).exclude(email=""):
        _, created = EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={"verified": True, "primary": True},
        )
        if created:
            fixed.append(user.email)

    if not fixed:
        return report(ALREADY, "подтверждённые адреса на месте")
    return report(CHANGED, f"подтверждён адрес: {', '.join(fixed)}")


# The steps, in the order they run. Each one is independent: it works out
# what it needs from the database rather than from the step before it.
STEPS = (ensure_superuser, ensure_named_superusers, ensure_verified_emails)

MARKS = {CHANGED: "+", ALREADY: "=", SKIPPED: "!"}


class Command(BaseCommand):
    help = "Довести базу до минимально работоспособного состояния (идемпотентно)"

    def handle(self, *args, **options):
        styles = {
            CHANGED: self.style.SUCCESS,
            ALREADY: lambda text: text,
            SKIPPED: self.style.WARNING,
        }

        self.stdout.write("bootstrap:")
        for step in STEPS:
            with transaction.atomic():
                state, message = step()
            self.stdout.write(f"  {MARKS[state]} {styles[state](message)}")
