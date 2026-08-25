"""
Семья: кто чей родитель и о чём родитель говорит с учителем.

Отдельное приложение, а не поле у пользователя, по той же причине, по какой
`schedule.CourseStudent` — таблица, а не список в курсе: связь тут **пара**, и
у пары есть своя жизнь. Родителей у ребёнка двое и они независимы, детей у
родителя сколько угодно, связь заводит и снимает администратор школы, а
разговор с учителем висит на конкретном родителе — всё это вопросы к строке, а
не к человеку.

`accounts` при этом остаётся про вход, `schools` — про заведение школы и
приглашения. Родство не то и не другое: оно про людей, которые уже вошли.
"""

from config.errors import Codes, api_error
from django.conf import settings
from django.db import models


class Guardianship(models.Model):
    """
    Пара «взрослый и ребёнок». Третья таблица той же формы, что назначение
    учителя и зачисление ученика, — и это не совпадение: все три отвечают на
    вопрос «кто с кем связан», и форму лучше держать одну.

    **Мама и папа — две строки, а не одна.** Соблазн завести «родителей» одной
    записью с двумя адресами большой, и он неверен: у сообщения есть автор, у
    прочтения — читатель, у оповещения — получатель, и ответить на эти вопросы
    про «родителя вообще» нельзя. Две строки на одного ребёнка — обычное
    состояние, а не дубль.

    **Строка удаляется, в отличие от зачисления.** У ученика строка курса — это
    право видеть сделанное, и снятие её сохраняет (`removed_at`); здесь
    хранить нечего: родство ошибочно записали или человек перестал быть
    представителем ребёнка, и «бывшее родство» — не состояние, о котором
    кто-то спросит. Разговоры при этом остаются: они принадлежат людям, а не
    строке (`PROTECT` на родителе тут не нужен — сообщения ссылаются на
    пользователей напрямую).
    """

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="children_links",
        on_delete=models.CASCADE,
        verbose_name="parent",
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="parent_links",
        on_delete=models.CASCADE,
        verbose_name="child",
    )
    # Кем приходится: слово родителя о себе, а не наша классификация. Пусто —
    # рабочее состояние: «представитель» бывает и без уточнения, а угадывать по
    # имени мы не будем.
    relation = models.CharField(
        "relation",
        max_length=32,
        blank=True,
        default="",
        help_text="«мама», «папа», «опекун». Пусто — просто представитель.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "guardianship"
        verbose_name_plural = "guardianships"
        ordering = ("child__last_name", "child__email", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("parent", "child"), name="one_link_per_parent_and_child"
            ),
            # Сам себе родитель — не опечатка данных, а сломанный обход: такая
            # строка сделала бы ученика собственным представителем и открыла
            # бы ему родительские разделы.
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("child")),
                name="nobody_is_their_own_parent",
            ),
        ]

    def __str__(self):
        return f"{self.parent} → {self.child}"


def link(parent, child, *, relation: str = "") -> "Guardianship":
    """
    Связать родителя с ребёнком, проверив то, что база проверить не может.

    Виды и школа лежат на пользователях, а не на строке, поэтому ограничением
    их не выразить — а перепутать легко: администратор ищет человека по имени,
    и однофамилец-учитель в списке стоит рядом с учеником.
    """
    if not parent.is_parent:
        api_error(
            Codes.NOT_A_PARENT,
            "Only a parent account can be linked as a parent.",
            field="parent",
        )
    if not child.is_student:
        api_error(
            Codes.NOT_A_STUDENT,
            "Only a student account can be linked as a child.",
            field="child",
        )
    if parent.school_id != child.school_id:
        api_error(
            Codes.DIFFERENT_SCHOOLS,
            "A parent and a child have to belong to the same school.",
            field="child",
        )

    row, _ = Guardianship.objects.get_or_create(
        parent=parent, child=child, defaults={"relation": relation}
    )
    return row
