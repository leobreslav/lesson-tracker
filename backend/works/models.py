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

# потолок шкалы: сотня покрывает и пятибалльную, и стобалльную, и MYP.
# Ограничение здесь только затем, чтобы опечатка в поле не превратилась в
# шкалу до миллиона
MAX_MARK = 100

# сколько критериев можно назначить одной работе: у MYP их четыре, у самой
# подробной рубрики — единицы. Число здесь только против опечатки
MAX_CRITERIA = 12

# скан класса — это десятки страниц, и он крупнее обычного вложения (20 МБ).
# Потолок здесь не про диск, а про воркер: файл читается в память целиком,
# а воркеров у прода два
MAX_SCAN_BYTES = 60 * 1024 * 1024

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

    **Бумажная работа — та же работа, у которой не задействованы задачи и
    отправки**, а у каждого ученика лежит скан. Различаются виды работ тем,
    какие части заняты, а не природой — как и домашка с практикой. Признак
    всё же явный (`on_paper`): пустая онлайн-работа, где задачи ещё не
    написаны, и пустая бумажная, где сканы ещё не загружены, в данных
    неразличимы, а показывать ученику надо разное. Вывести не из чего —
    значит надо хранить.

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
    description = models.TextField(
        "description",
        blank=True,
        help_text=(
            "Что делать: текст работы целиком. У домашнего задания это оно и "
            "есть, у контрольной — обычно пусто."
        ),
    )
    is_homework = models.BooleanField(
        "homework",
        default=False,
        help_text=(
            "Задано на дом. Отдельная работа от классной ничем, кроме этого, "
            "не отличается — признак нужен, чтобы показать её в своём разделе "
            "урока: пустая домашняя и пустая классная в данных неразличимы."
        ),
    )
    on_paper = models.BooleanField(
        "written on paper",
        default=False,
        help_text=(
            "Работа написана на бумаге: задач и отправок у неё нет, у "
            "каждого ученика скан."
        ),
    )
    slot = models.ForeignKey(
        "schedule.Slot",
        related_name="works",
        null=True,
        blank=True,
        # час могут удалить (переставили расписание), и работа это
        # переживает: она про то, что уже решали
        on_delete=models.SET_NULL,
        verbose_name="set at",
        help_text=(
            "Занятие, на котором работу задали. Не «когда сдавать» — на это "
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


class Criterion(models.Model):
    """
    Строка шкалы работы: по чему её оценивают и до скольки.

    Отдельного поля «как оценивается» у работы нет, и это не экономия:
    **оценивание есть тогда, когда есть критерии**. Не оценивается — их
    ноль; обычная отметка — один критерий без имени; MYP — четыре с
    именами. Три состояния выражаются одними данными, и рассогласоваться с
    флагом не могут.

    Одно следствие для интерфейса: «один безымянный критерий» он показывает
    как обычное поле оценки, а не как список из одной строки. Правило
    однозначное — имя пустое и критерий один.

    Расширять шкалу дальше (буквы, «зачёт/незачёт») можно добавлением вида
    критерия: значения уже лежат по строкам, и переливать их не придётся —
    ровно ради этого форма выбрана такой.
    """

    work = models.ForeignKey(
        Work,
        related_name="criteria",
        on_delete=models.CASCADE,
        verbose_name="work",
    )
    position = models.PositiveIntegerField("position", default=0)
    name = models.CharField(
        "name",
        max_length=100,
        blank=True,
        help_text="Пустое у обычной отметки; «Критерий A» и подобное — у MYP.",
    )
    maximum = models.PositiveSmallIntegerField(
        "maximum",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_MARK)],
        help_text="Верх шкалы: 5, 8, 100 — как решила школа.",
    )

    class Meta:
        verbose_name = "grading criterion"
        verbose_name_plural = "grading criteria"
        ordering = ("position", "id")

    def __str__(self):
        return self.name or f"0–{self.maximum}"


class StudentWork(models.Model):
    """
    Работа одного ученика: то, что он сдал, и что за это получил.

    Строки не хватало с самого начала, и обнаружилось это на бумажной
    контрольной: всё ученическое лежало на `Submission` — отправке
    **задачи**, — а у работы на бумаге отправок нет вовсе, зато есть скан и
    оценка. Оценка и не могла лежать на отправке: она про работу целиком.

    Заводится по требованию: пока учитель ничего не поставил и ученик ничего
    не сдал, строки нет. Список в интерфейсе строится по составу курса, а не
    по этим строкам, поэтому «ещё не проверен» и «строки нет» — одно и то же
    состояние, и держать его в базе незачем.
    """

    work = models.ForeignKey(
        Work,
        related_name="students",
        on_delete=models.CASCADE,
        verbose_name="work",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="student_works",
        on_delete=models.CASCADE,
        verbose_name="student",
    )
    comment = models.TextField(
        "comment",
        blank=True,
        help_text="Слова учителя об этой работе. Бывают и без оценки.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "student's work"
        verbose_name_plural = "students' works"
        ordering = ("student__last_name", "student__email")
        constraints = [
            models.UniqueConstraint(
                fields=("work", "student"), name="one_row_per_student_per_work"
            ),
        ]

    def __str__(self):
        return f"{self.student} — {self.work}"


class Mark(models.Model):
    """
    Оценка по одному критерию. Текущее значение, и только оно.

    История лежит рядом (`MarkChange`) и пишется с первого дня: исправленная
    отметка в журнале — это событие, а не новое значение поля, и
    восстановить её задним числом было бы неоткуда. Дублирование намеренное:
    читают все текущее, а историю спрашивают редко и по одной работе.
    """

    student_work = models.ForeignKey(
        StudentWork,
        related_name="marks",
        on_delete=models.CASCADE,
        verbose_name="student's work",
    )
    criterion = models.ForeignKey(
        Criterion,
        related_name="marks",
        on_delete=models.CASCADE,
        verbose_name="criterion",
    )
    value = models.PositiveSmallIntegerField(
        "value", validators=[MaxValueValidator(MAX_MARK)]
    )

    class Meta:
        verbose_name = "mark"
        verbose_name_plural = "marks"
        ordering = ("criterion__position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("student_work", "criterion"), name="one_mark_per_criterion"
            ),
        ]

    def __str__(self):
        return f"{self.value}/{self.criterion.maximum}"


class MarkChange(models.Model):
    """
    Кто и когда поменял оценку. Дописывается, не правится.

    `value` пустое значит «снял отметку». Кто поменял — `SET_NULL`: человек
    может уйти из школы, а запись в журнале остаётся его записью.
    """

    student_work = models.ForeignKey(
        StudentWork,
        related_name="changes",
        on_delete=models.CASCADE,
        verbose_name="student's work",
    )
    criterion = models.ForeignKey(
        Criterion,
        related_name="changes",
        on_delete=models.CASCADE,
        verbose_name="criterion",
    )
    value = models.PositiveSmallIntegerField("value", null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mark_changes",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="changed by",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mark change"
        verbose_name_plural = "mark changes"
        ordering = ("changed_at", "id")

    def __str__(self):
        return f"{self.criterion}: {self.value}"
