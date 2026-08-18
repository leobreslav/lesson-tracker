from accounts.models import Kind
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

    **Приглашение расходуется однажды.** Оно вдобавок называет курсы,
    которые ждут человека к первому входу: ученика в них записывают,
    учителю их поручают. Дальше и то и другое — прямое действие
    администратора: если бы приглашение доносило курсы при каждом входе,
    снятый с курса возвращался бы в него сам, стоило ему войти.

    Поэтому и правило вставки такое: есть учётка — записываем немедленно,
    нет — записываем сюда и ждём.
    """

    school = models.ForeignKey(
        School,
        related_name="invitations",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    email = models.EmailField("email address")
    name = models.CharField(
        "name as written down",
        max_length=200,
        blank=True,
        help_text=(
            "Как администратор назвал человека при вводе. Ярлык для списка "
            "ожидающих, а не имя учётки: имя приходит из Google при первом "
            "входе."
        ),
    )
    kind = models.CharField(
        "kind",
        max_length=8,
        choices=Kind,
        default=Kind.TEACHER,
        help_text="Кем человек войдёт: учителем или учеником.",
    )
    is_school_admin = models.BooleanField("grants the admin role", default=False)
    courses = models.ManyToManyField(
        "schedule.Course",
        related_name="pending_invitations",
        blank=True,
        verbose_name="courses to join on first sign-in",
        help_text=(
            "Курсы, которые ждут человека к первому входу. У ученика это "
            "«куда записать», у учителя — «что вести»: назначить курс "
            "приглашённому надо в тот же день, когда раздают нагрузку, а не "
            "когда он соберётся войти."
        ),
    )
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
            # ученик не бывает администратором школы: роль про общие объекты
            # школы, а он в них не заходит вовсе
            models.CheckConstraint(
                condition=~models.Q(kind="student", is_school_admin=True),
                name="student_invitation_grants_no_role",
            ),
        ]

    def __str__(self):
        return f"{self.email} → {self.school}"

    @property
    def is_accepted(self) -> bool:
        return self.accepted_at is not None
