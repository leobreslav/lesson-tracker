"""
Разговор двух людей.

Собеседник не меняет природу разговора: коллега, ученик, родитель — это одна
вещь функционально, и три таблицы под неё были бы тремя ответами на один
вопрос. Отличается не собеседник, а **повод**, и повод здесь ровно один
необязательный — ребёнок, о котором говорят взрослые.

Сообщение при этом своей таблицы не заводит: она есть, и заведена была
заранее — `works.Message` с ограничением «ровно один владелец». Владельцев у
неё стало три: тред о задаче, заметка на снимке и вот этот разговор. В
докстринге той модели это записано прямо, ещё до появления чата: «чат будет
читать сообщения, сгруппированные по собеседнику».
"""

from django.conf import settings
from django.db import models


class Talk(models.Model):
    """
    Разговор двоих: коллеги о работе, родитель с учителем о ребёнке, ученик с
    учителем о себе.

    **Пара нормализована по номеру** (`lower` < `upper`), и это не украшение:
    «Иванова с Петровым» и «Петров с Ивановой» — один разговор, а без
    нормализации первый же ответ завёл бы второй. Ограничение базы, а не
    договорённость: договорённость забывается в том месте, где заводят
    разговор вторым путём.

    **Ребёнок — повод, а не участник.** Мама и папа пишут порознь, и сваливать
    их в один разговор значило бы показывать каждому чужую переписку; ребёнок
    же в этом разговоре не участвует вовсе — он его предмет. Пусто — разговор
    без повода: так говорят коллеги, и так же ученик говорит с учителем о
    себе.

    **Школа названа прямо**, хотя её можно вывести из участников: разговор не
    выходит за школу, и выборка «мои разговоры» не должна ради этой проверки
    ходить в двух пользователей за каждой строкой.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="talks",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    lower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="talks_as_lower",
        on_delete=models.CASCADE,
        verbose_name="one side",
    )
    upper = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="talks_as_upper",
        on_delete=models.CASCADE,
        verbose_name="the other side",
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="talks_about",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="child talked about",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # своя отметка, а не `auto_now`: правится не разговор, а его сообщение,
    # и всплывать в списке он должен по нему
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "talk"
        verbose_name_plural = "talks"
        ordering = ("-updated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(lower__lt=models.F("upper")),
                name="talk_sides_are_ordered",
            ),
            # Два ограничения вместо одного: NULL в Postgres не равен NULL, и
            # одна уникальность по тройке не запретила бы двух разговоров
            # коллег — у обоих повод пуст, а значит «различен».
            models.UniqueConstraint(
                fields=("lower", "upper"),
                condition=models.Q(child__isnull=True),
                name="one_talk_per_pair_without_a_child",
            ),
            models.UniqueConstraint(
                fields=("lower", "upper", "child"),
                condition=models.Q(child__isnull=False),
                name="one_talk_per_pair_and_child",
            ),
        ]

    def __str__(self):
        about = f" о {self.child}" if self.child_id else ""
        return f"{self.lower} ↔ {self.upper}{about}"

    def other_side(self, person):
        """Собеседник глазами этого человека."""
        return self.upper if person.pk == self.lower_id else self.lower
