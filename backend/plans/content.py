"""
What a lesson actually says, as opposed to what it is called.

Four fields, shared by a teacher's plan node and by a line of a library
template — the same shape on both sides, because a template is a snapshot of
a plan and anything one can hold the other has to hold too.

**Markdown is stored, never HTML.** Maths rides in `$…$` and `$$…$$`. That is
the whole reason there is no WYSIWYG editor here: the text has to survive
being exported and pasted into LaTeX, and an editor that owns the markup
would quietly stop it from doing that. Rendering happens in the browser and
nowhere else.

A section header has no content — it is a folder, not a lesson — which
`content_problems` says once for the models, the serializers and the admin.
"""

from django.db import models

CONTENT_FIELDS = ("objectives", "body", "formative", "homework")

# DRF's CharField trims surrounding whitespace, and Markdown *is* whitespace:
# a trailing blank line separates the last paragraph from whatever follows it
# when the text is pasted into LaTeX. Every serializer that carries these
# fields turns the trimming off through this.
CONTENT_EXTRA_KWARGS = {field: {"trim_whitespace": False} for field in CONTENT_FIELDS}


class LessonContent(models.Model):
    """Abstract: the four content fields and nothing else."""

    # MYP objectives the lesson works towards
    objectives = models.TextField("objectives", blank=True)
    # theory, problem statements — the body of the lesson
    body = models.TextField("body", blank=True)
    # a short check, done in the lesson
    formative = models.TextField("formative check", blank=True)
    homework = models.TextField("homework", blank=True)

    class Meta:
        abstract = True

    @property
    def has_content(self) -> bool:
        return any(getattr(self, name) for name in CONTENT_FIELDS)


def content_problems(*, is_section: bool, values) -> dict:
    """
    `{field: message}` for content put where it cannot live; empty is fine.

    `values` is anything that answers to `.get(field)` — a validated payload
    or a model instance wrapped in a dict.
    """
    if not is_section:
        return {}

    return {
        field: "A section header holds no lesson content."
        for field in CONTENT_FIELDS
        if values.get(field)
    }
