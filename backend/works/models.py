"""
Работы онлайн: контрольные, проверочные, домашние задания.

Одна модель на все три: различаются они настройками, а не природой, и
отдельные сущности разошлись бы в первый же месяц — «а можно ли у домашки
несколько попыток».

Четыре решения записаны здесь, потому что на них стоит весь остальной код.

**Статуса «черновик» нет.** Работа видна ученику ровно тогда, когда открыто
её окно времени: составил заранее с окном в будущем — она скрыта сама.
Статус рядом с окном означал бы два источника правды об одном и том же, и
рано или поздно они разошлись бы.

**Попытка расходуется на любой отправке**, проверил её учитель или нет.
Иначе право ученика на ответ зависело бы от того, как быстро учитель дошёл
до его ячейки, — правило, которое ученик не может проверить сам.

**Ничего не перезаписывается.** Отправка — строка журнала, а не поле со
значением: вторая попытка не затирает первую, и «что он писал сначала»
остаётся вопросом с ответом.

**Ответ хранится ровно как введён.** Никакой нормализации при сохранении:
автопроверки ещё нет, и когда она появится, обрабатывать надо будет при
сравнении. Один `strip()` в `save()` — и восстановить исходное уже неоткуда.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

# сколько попыток разрешено назначить: больше — уже не попытки, а
# «отправляй сколько хочешь», и для этого есть пустое поле
MAX_ATTEMPTS = 20

# состояния работы; четвёртого нет и не должно быть
PLANNED, OPEN, CLOSED = "planned", "open", "closed"


class Work(models.Model):
    """
    Работа курса: окно времени, попытки и список задач.

    Работа принадлежит **курсу**, как и план. Личной она была, пока курс
    могли вести двое: тогда общая работа означала бы, что правку одного
    видит группа другого. Ведущий у курса теперь один, и обоснование ушло
    вместе с ним, а вот цена личной работы осталась бы: ученик зачислен на
    курс, видимость работ считается по курсу, и после смены ведущего
    контрольные предшественника висели бы у всех на виду — читать их можно,
    а доправить условие или проверить неотмеченные ответы некому.

    Кто составил, помним (`created_by`), но это история, а не владение:
    поле `SET_NULL`, и уход человека из школы работу не уносит. Раньше там
    стоял `CASCADE`, то есть удаление учётки учителя стирало заодно все
    отправки учеников и все отметки.

    Проверка при этом остаётся именным действием: у отправки есть
    `checked_by`, и кто поставил отметку, видно всегда.

    Привязка к **уроку** необязательна и означает «на каком уроке задали».
    Раньше она указывала на строку плана, и это была не та связь: план —
    программа, он переживает год и уезжает на полку, а «практика 12 марта»
    — факт этого года. Плюс раскладка позиционная: вставили урок в
    сентябрьскую тему в марте, и строка плана уехала бы вместе с работой.
    """

    course = models.ForeignKey(
        "schedule.Course",
        related_name="works",
        # PROTECT, как у расписания и плана: администратор не должен снести
        # чужие контрольные, удалив курс
        on_delete=models.PROTECT,
        verbose_name="course",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="works",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="created by",
    )
    title = models.CharField("title", max_length=200)
    opens_at = models.DateTimeField(
        "opens at",
        help_text="До этого момента работы для ученика не существует.",
    )
    closes_at = models.DateTimeField(
        "closes at",
        help_text="После этого момента ответы не принимаются, но всё видно.",
    )
    attempts = models.PositiveSmallIntegerField(
        "attempts per task",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_ATTEMPTS)],
        help_text="Пусто — без ограничения. Считается по задаче, не по работе.",
    )
    show_result = models.BooleanField(
        "show the verdict to the student",
        default=True,
        help_text=(
            "Видит ли ученик отметку учителя сразу, как только она "
            "поставлена. Выключено — увидит после закрытия окна."
        ),
    )
    lesson = models.ForeignKey(
        "schedule.Lesson",
        related_name="works",
        null=True,
        blank=True,
        # урок могут удалить (переставили расписание), и работа это
        # переживает: она про то, что уже решали
        on_delete=models.SET_NULL,
        verbose_name="lesson",
        help_text=(
            "Урок, на котором работу задали. Не «когда сдавать» — на это "
            "отвечает окно времени."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "work"
        verbose_name_plural = "works"
        ordering = ("-opens_at", "-id")
        indexes = [
            models.Index(fields=("course", "opens_at"), name="work_course_opens_idx"),
            models.Index(fields=("course", "id"), name="work_course_idx"),
        ]

    def __str__(self):
        return self.title

    def state(self, now=None) -> str:
        """`planned` → `open` → `closed`; больше состояний у работы нет."""
        now = now or timezone.now()
        if now < self.opens_at:
            return PLANNED
        if now > self.closes_at:
            return CLOSED
        return OPEN

    @property
    def is_open(self) -> bool:
        return self.state() == OPEN


class Task(models.Model):
    """
    Задача внутри работы: условие и список допустимых ответов.

    Модель сознательно бедная — она будет расти. Ответов несколько, потому
    что «x+3» и «3+x» одинаково верны; пока автопроверки нет, список — то,
    с чем сверяется глазами учитель.

    Пустой список законен: задача, у которой эталона нет вовсе и которую всё
    равно проверяют руками.
    """

    work = models.ForeignKey(
        Work,
        related_name="tasks",
        on_delete=models.CASCADE,
        verbose_name="work",
    )
    position = models.PositiveIntegerField("position", default=0)
    question = models.TextField("question")
    answers = ArrayField(
        models.TextField(),
        default=list,
        blank=True,
        verbose_name="accepted answers",
        help_text="Хранятся ровно как введены: обработка — при сравнении.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "task"
        verbose_name_plural = "tasks"
        ordering = ("position", "id")

    def __str__(self):
        return self.question[:50]


class Submission(models.Model):
    """
    Одна отправка ответа. Строка журнала, а не значение поля.

    Вердикт живёт здесь же, а не отдельной моделью: он и есть свойство
    конкретной отправки — «этот ответ верен». Пришла новая отправка, у неё
    вердикта нет, и ячейка честно возвращается в «не проверено». Отдельная
    модель добавила бы join ради того же самого и соблазн «перевесить
    вердикт на новую попытку», чего делать как раз нельзя.
    """

    task = models.ForeignKey(
        Task,
        related_name="submissions",
        on_delete=models.CASCADE,
        verbose_name="task",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="submissions",
        on_delete=models.CASCADE,
        verbose_name="student",
    )
    answer = models.TextField("answer as it was typed", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_correct = models.BooleanField(
        "verdict",
        null=True,
        blank=True,
        help_text="Пусто — не проверено. Смена отметки попытку не расходует.",
    )
    checked_at = models.DateTimeField("checked at", null=True, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="checked_submissions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="checked by",
    )

    class Meta:
        verbose_name = "submission"
        verbose_name_plural = "submissions"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("task", "student", "created_at"), name="submission_cell_idx"
            ),
        ]

    def __str__(self):
        return f"{self.student}: {self.answer[:30]}"

    @property
    def is_checked(self) -> bool:
        return self.is_correct is not None
