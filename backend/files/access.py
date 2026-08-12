"""
Who may see and change an attachment.

The rule is about the **attachment**, not about the file behind it. One
`StoredFile` can serve a template on the school's shelf and a dozen personal
plans; a teacher may reach it through their own lesson and through the
published template, and not through a colleague's plan — even though all
three point at the very same object in the bucket. Asking "may you read this
file" would have no single answer; asking "may you read this reference" has.

Two refusals, as everywhere else in the project, but drawn slightly
differently here:

* another school — **404**. The attachment is out of the queryset and a
  stranger learns nothing;
* one's own school, someone else's lesson — **403** with a code. Inside a
  school people already know their colleagues exist, and "not yours" is a
  more useful answer than pretending the id is free.
"""

from django.db.models import Q
from library.models import PlanTemplateRow
from library.serializers import visible_templates
from plans.models import PlanNode

from .models import Attachment


def school_attachments(user):
    """Everything hanging off a lesson row of this person's school."""
    if user is None or not user.is_authenticated or user.school_id is None:
        return Attachment.objects.none()

    return Attachment.objects.filter(
        Q(plan_row__teacher__school_id=user.school_id)
        | Q(template_row__template__school_id=user.school_id)
    )


def readable_attachments(user):
    """
    What may appear in a list: one's own lessons, and templates open to one.

    A colleague's draft is absent here for the same reason it is absent from
    the library list — not hidden, not there.
    """
    if user is None or not user.is_authenticated or user.school_id is None:
        return Attachment.objects.none()

    return Attachment.objects.filter(
        Q(plan_row__teacher=user)
        | Q(template_row__template__in=visible_templates(user))
    )


def can_read(user, attachment) -> bool:
    if attachment.plan_row_id is not None:
        return attachment.plan_row.teacher_id == user.pk

    template = attachment.template_row.template
    return template.school_id == user.school_id and (
        template.is_published or template.author_id == user.pk
    )


def can_write(user, attachment) -> bool:
    """
    Changing a reference is changing the lesson it hangs off.

    A school administrator may throw a whole template off the shelf, but not
    edit somebody's lesson line by line — so authorship, not the role, is
    what counts here.
    """
    if attachment.plan_row_id is not None:
        return attachment.plan_row.teacher_id == user.pk

    return attachment.template_row.template.author_id == user.pk


def writable_plan_rows(user):
    """Plan lessons this person may attach something to. Headers cannot."""
    if user is None or not user.is_authenticated:
        return PlanNode.objects.none()
    return PlanNode.objects.filter(teacher=user, is_section=False)


def writable_template_rows(user):
    if user is None or not user.is_authenticated or user.school_id is None:
        return PlanTemplateRow.objects.none()

    return PlanTemplateRow.objects.filter(
        template__author=user,
        template__school_id=user.school_id,
        is_header=False,
    )
