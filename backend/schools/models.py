from django.conf import settings
from django.db import models


class School(models.Model):
    """
    A school: the boundary everything shared is scoped to.

    The calendar, its markup and the list of courses belong to the school and
    are edited by its administrators; what a teacher does inside those courses
    — the lesson slots and the plan — stays personal.
    """

    name = models.CharField("name", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "school"
        verbose_name_plural = "schools"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Invitation(models.Model):
    """
    An invitation to a school, written before the person first signs in.

    An administrator types an email address in advance; when somebody signs in
    through Google, the invitation is looked up by the address Google itself
    verified. Matching a self-typed address would let anyone claim a
    colleague's invitation, so the check runs against the provider's data.

    Accepting stamps `accepted_at` and keeps the row: it is the record of who
    invited whom and when.
    """

    school = models.ForeignKey(
        School,
        related_name="invitations",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    email = models.EmailField("email address")
    is_school_admin = models.BooleanField("grants the admin role", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="sent_invitations",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="invited by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField("accepted at", null=True, blank=True)

    class Meta:
        verbose_name = "invitation"
        verbose_name_plural = "invitations"
        ordering = ("-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("school", "email"), name="unique_invitation_per_school"
            ),
        ]

    def __str__(self):
        return f"{self.email} → {self.school}"

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None


class SubjectMethodist(models.Model):
    """
    Полномочие утверждать планы по предмету — не ступень иерархии.

    Методист это тот же учитель со своими курсами и своим планом; ему
    дополнительно можно прислать план на утверждение. Поэтому роль висит не
    на человеке (как `is_school_admin`), а на паре «человек и предмет»:
    методистов по алгебре может быть двое, а один человек может отвечать за
    алгебру и геометрию сразу.

    Назначает администратор школы. Сам он утверждать не может — если только
    его тоже не назначили: администратор распоряжается школой, а не
    содержанием предмета.
    """

    school = models.ForeignKey(
        School,
        related_name="methodists",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="methodist_of",
        on_delete=models.CASCADE,
        verbose_name="teacher",
    )
    subject = models.ForeignKey(
        "schedule.Subject",
        related_name="methodists",
        on_delete=models.CASCADE,
        verbose_name="subject",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="methodists_assigned",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="assigned by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "subject methodist"
        verbose_name_plural = "subject methodists"
        ordering = ("subject__name", "user__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "subject"), name="one_methodist_row_per_subject"
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.subject}"
