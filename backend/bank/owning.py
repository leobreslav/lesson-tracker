"""
Три уровня владения, одной парой полей.

    школа = null,  автор = null   → системный каталог  (правит суперпользователь)
    школа = есть,  автор = null   → школьный           (правят администраторы)
    школа = есть,  автор = есть   → личный             (правит автор)

Лестница читается сверху вниз: чем выше, тем шире видно и тем уже круг
правящих. Тот же приём, что у вложения с его тремя владельцами, — и по той же
причине: право и видимость выражаются **данными**, а не флагом «вид записи»,
который однажды разойдётся с полями.

`created_by` к этому отношения не имеет и хранится отдельно: это **история**,
а не право. Человек ушёл из школы — запись осталась, а знать, чьих она рук,
полезно. Мы это уже проходили с работами, где авторство пришлось развести с
принадлежностью курсу.
"""

from django.conf import settings
from django.db import models

SYSTEM = "system"
SCHOOL = "school"
PERSONAL = "personal"


class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Что человек вправе видеть: системное — все, школьное — своя школа,
        личное — только автор.
        """
        if user.is_superuser:
            return self

        return self.filter(
            models.Q(school__isnull=True)
            | models.Q(school=user.school, owner__isnull=True)
            | models.Q(school=user.school, owner=user)
        )

    def writable_by(self, user):
        """
        Кто правит: системное — суперпользователь, школьное и личное —
        администратор школы (он школьный суперпользователь и правит в школе
        всё), личное — ещё и автор.
        """
        if user.is_superuser:
            return self
        if not user.school_id:
            return self.none()
        if user.is_school_admin:
            return self.filter(school=user.school)

        return self.filter(school=user.school, owner=user)


class Owned(models.Model):
    """Общие поля владения. Наследуется каталогами банка."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="school; empty means the system catalogue",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="owner; empty means the whole school",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="who created it",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def level(self) -> str:
        if self.school_id is None:
            return SYSTEM
        return PERSONAL if self.owner_id else SCHOOL


def writable_ids(model, user, rows) -> set[int]:
    """
    Кто из этих строк правится — **одним** запросом, а не по строке.

    Список отдаёт `may_edit` у каждой записи: без него интерфейс не знает, кому
    рисовать карандаш. Спрошенное построчно это запрос на строку, и растёт оно
    ровно там, где полка большая, — то есть у того, ради кого полку и завели.
    """
    ids = [row.pk for row in rows]
    return set(
        model.objects.writable_by(user)
        .filter(pk__in=ids)
        .values_list("pk", flat=True)
    )
