"""
What a new school gets on its first day.

A school with nothing in it cannot have a course created in it: a course
wants a grade level, and the list of levels starts out empty. Somebody would
have to type eleven rows before the first «9B Algebra» — so they are made
here instead, and the administrator edits the names afterwards.

A signal rather than a call inside the viewset because a school is created
from more than one place: the superuser section, /admin/, `seed_demo` and
every test fixture. A default that only appears on one of those paths is not
a default.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import School

# «Grade N» for every year of study: neutral, sortable and obviously meant to
# be renamed. Schools that number their years differently — MYP, «10 класс» —
# rename them and keep the level, which is what everything sorts on.
DEFAULT_GRADE_RANGE = range(1, 12)


def default_grade_levels(school):
    """The starting list of year groups. Idempotent: existing levels stay."""
    from schedule.models import GradeLevel

    existing = set(
        GradeLevel.objects.filter(school=school).values_list("level", flat=True)
    )

    return GradeLevel.objects.bulk_create(
        [
            GradeLevel(school=school, level=level, name=f"Grade {level}")
            for level in DEFAULT_GRADE_RANGE
            if level not in existing
        ]
    )


@receiver(post_save, sender=School, dispatch_uid="schools.default_grade_levels")
def on_school_created(sender, instance, created, **kwargs):
    if created:
        default_grade_levels(instance)
