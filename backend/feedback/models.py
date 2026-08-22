from django.conf import settings
from django.db import models


class Message(models.Model):
    """
    Сообщение разработчику: «сломалось» или «хорошо бы».

    Единственная таблица в проекте, которая **не принадлежит школе**. Всё
    остальное здесь чьё-то: курс, план, работа, — а это разговор пользователя
    с тем, кто пишет программу, и школа в нём только обстоятельство. Поэтому
    и читает их суперпользователь, а не администратор школы: администратор
    правит школу, а не приложение, и чужие жалобы на интерфейс ему не адресат.

    **Пишут его оба вида пользователей.** Ученик видит ровно те же поломки,
    что учитель, а сказать о них ему было нечем вовсе — и это худший случай:
    человек, у которого не работает, молчит, потому что некому.

    Хранится **текстом, а не разобранным по полям**. Форма из десяти полей
    («что нажали», «что ожидали», «версия браузера») — инструмент для того,
    кто умеет заполнять баг-репорты; здесь пишут учителя между уроками, и
    пустая форма отпугнёт вернее любой сложности. Всё, что можно узнать не
    спрашивая, узнаётся не спрашивая: адрес страницы, кто, когда, какая школа.
    """

    class Kind(models.TextChoices):
        BUG = "bug", "об ошибке"
        IDEA = "idea", "предложение"

    kind = models.CharField(
        "kind", max_length=8, choices=Kind.choices, default=Kind.BUG
    )
    text = models.TextField("text", max_length=4000)
    # автор остаётся вопросом «с кем говорить», и уход человека из школы его
    # не отменяет: сообщение живёт дольше учётки, и отвязанное от неё оно
    # всё ещё осмысленно
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="feedback",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="author",
    )
    school = models.ForeignKey(
        "schools.School",
        related_name="feedback",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="school",
    )
    # откуда написали: половина сообщений об ошибке — «тут ничего не
    # работает», и без адреса страницы искать это негде
    page = models.CharField("page", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # «разобрано» — не статус из четырёх состояний, а отметка: сообщение либо
    # ждёт, либо уже унесено в работу. Три состояния завели бы вопрос, чем
    # «в работе» отличается от «принято», а отвечать на него некому
    handled_at = models.DateTimeField("handled at", null=True, blank=True)

    class Meta:
        verbose_name = "feedback message"
        verbose_name_plural = "feedback messages"
        # новые сверху: список читают сверху вниз и до первого знакомого
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("handled_at", "-created_at"))]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.text[:40]}"
