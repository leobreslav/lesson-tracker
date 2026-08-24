"""
След каждого вызова модели: кто, за что и сколько это стоило.

Запись здесь — не отчётность ради отчётности. Расход идёт с ключа школы, и у
двух вопросов о нём разные хозяева: администратор спрашивает «сколько школа
потратила и не пора ли поднять потолок», учитель — «сколько стоила вот эта
пачка сканов». Один и тот же журнал отвечает обоим, просто сужается по
пользователю.

Хранится **микродоллар** (миллионная доля), потому что вызов стоит доли цента:
в центах вся история округлилась бы в ноль.
"""

from django.conf import settings
from django.db import models


class AiSpend(models.Model):
    """Один вызов модели. Строки не правятся и не удаляются — это журнал."""

    SCAN_HEADER = "scan_header"
    SCAN_REREAD = "scan_reread"
    SCAN_QUESTIONS = "scan_questions"
    SCAN_SECOND = "scan_second"
    PURPOSES = [
        (SCAN_HEADER, "reading a scanned blank header"),
        (SCAN_REREAD, "re-reading a header the two readers disagreed about"),
        (SCAN_QUESTIONS, "copying the questions off the question paper"),
        (SCAN_SECOND, "a second reader on the same header"),
    ]

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="ai_spend",
        verbose_name="school",
    )
    # Человек уходит из школы, а расход остаётся: он про деньги школы, а не
    # про него. Поэтому SET_NULL, а не каскад.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_spend",
        verbose_name="who spent it",
    )
    # То же и с работой: её могут удалить, а трата была.
    work = models.ForeignKey(
        "works.Work",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_spend",
        verbose_name="work",
    )
    purpose = models.CharField("purpose", max_length=32, choices=PURPOSES)
    model = models.CharField("model", max_length=64)
    input_tokens = models.PositiveIntegerField("input tokens", default=0)
    output_tokens = models.PositiveIntegerField("output tokens", default=0)
    cost_micros = models.PositiveIntegerField("cost, millionths of a dollar", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI spend"
        verbose_name_plural = "AI spend"
        ordering = ("-created_at",)
        indexes = [
            # Потолок считается за календарный месяц, и считается на каждый
            # вызов: без индекса это полный проход по журналу школы.
            models.Index(fields=["school", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.school_id}: {self.purpose} {self.cost_micros}µ$"
