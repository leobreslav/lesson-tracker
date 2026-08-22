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
    `checked_by`, и кто поставил отметку, видно всегда. Сама отметка —
    балл (`Mark`) со ссылкой на этот ответ; полем отправки она была, пока
    вердикт был галочкой.

    **Бумажная работа — та же работа, у которой не задействованы отправки**,
    а у каждого ученика лежит скан. Различаются виды работ тем, какие части
    заняты, а не природой — как и домашка с практикой.

    Своего признака у неё нет и больше не нужно. Флагом работы (`on_paper`)
    он был, и отвечал ровно на один вопрос — принимаются ли ответы онлайн, —
    но ответ был один на всю работу разом. Теперь на него отвечает **ячейка**
    (`Task.open_for_answers`), и «Q1 и Q2 решайте онлайн, Q3 сдайте на листе»
    стало выразимым. Бумажная работа — это работа, у которой закрыты все
    ячейки; вопрос «а какая она вообще» перестал существовать вместе с
    флагом.

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
    # Как из этой работы получается отметка. Выбирает учитель, на каждой
    # работе свою; пусто — законное состояние: баллы есть, отметки нет.
    grading_system = models.ForeignKey(
        "works.GradingSystem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="works",
        verbose_name="grading system",
    )
    # Считается ли работа в итог за период. Формативную оценивают как придётся
    # — и в итог она не идёт; это не то же самое, что «домашняя».
    is_summative = models.BooleanField(
        "counts towards the term result",
        default=False,
        help_text="Формативную оценивают как придётся, и в итог она не идёт.",
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
    Ячейка работы: место, цена в баллах и ссылка на условие.

    Своего текста у ячейки нет ни одного поля, и это главное решение здесь.
    Задача, набранная в работе на бегу, и задача из общего каталога — **одно
    и то же**: условие. Разница только в том, где оно лежит: у одной есть
    строка в книге, у другой нет, а лежит она в самой работе — как в
    источнике. Отдельного признака «черновая» поэтому не заводится: он был бы
    вторым источником правды о том же самом.

    Что своё у ячейки, а что у условия:

    | у ячейки | у условия |
    |----------|-----------|
    | позиция, цена в баллах | текст, ответы, теги, аналоги |
    | отправки, попытки, вердикты, оценки | владение и происхождение |

    Отсюда следствие, которое стоит помнить: **попытки не складываются**. Одно
    условие, спрошенное в контрольной и в домашней, даёт две ячейки, и у
    каждой свой счёт — иначе первая работа съедала бы попытки у второй.

    **Условия может не быть вовсе.** Пустая ячейка — это ячейка без условия, а
    не условие с пустым текстом: так выражается `Q1…Qn` бумажной работы, где
    учитель ничего не вписывал, а лист лежит у ученика на парте.
    """

    work = models.ForeignKey(
        Work,
        related_name="tasks",
        on_delete=models.CASCADE,
        verbose_name="work",
    )
    position = models.PositiveIntegerField("position", default=0)
    # Условие. `PROTECT`, а не `SET_NULL`: условие, по которому писали, не
    # удаляется — снимается (`retired`). Иначе удаление опустошило бы ячейку
    # молча, и ответы учеников остались бы висеть под пустым местом.
    problem = models.ForeignKey(
        "bank.Problem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asked_in",
        verbose_name="statement",
    )
    # Сколько баллов стоит этот вопрос **в этой работе**. Свойство ячейки, а
    # не задачи: «2+2» стоит два балла в пятом классе и полбалла в девятом.
    maximum = models.PositiveSmallIntegerField("top mark for this question", default=1)
    # Показывать ли шапку сюжета вместе с этим пунктом.
    #
    # Свойство **ячейки**, а не условия: одна и та же задача в контрольной
    # идёт с данными, а в домашней без — учитель написал их на доске. Из
    # данных «дал устно» и «забыл» неразличимы, поэтому признак хранится, а не
    # выводится: тот же довод, что у `is_homework`.
    #
    # Тот же флаг решает и повтор: два пункта одного сюжета в одной работе
    # печатали бы шапку дважды, и у второй ячейки её выключают. Делать это
    # само мы не стали — порядок ячеек учитель меняет, и молча исчезнувшая
    # шапка у переехавшего вверх вопроса была бы угадыванием.
    #
    # У ячейки без сюжета флаг ничего не значит и не показывается.
    show_stem = models.BooleanField(
        "show the stem to the student", default=True
    )
    # Принимает ли этот вопрос ответы онлайн. Свойство **ячейки**, а не
    # работы: флагом работы это было (`on_paper`), и смешанный случай — «Q1 и
    # Q2 решайте онлайн, Q3 сдайте на листе» — был недостижим по построению.
    #
    # Вывести не из чего, и это тот же довод, что у `is_homework` и
    # `show_stem`: пустая ячейка бумажной работы и ещё не написанный вопрос
    # онлайновой в данных неразличимы, а ученику надо показывать разное.
    #
    # Открыто по умолчанию: работа, у которой вопросы созданы, но ни один не
    # открыт, выглядит для класса пустой — и обнаруживается это на уроке.
    # Закрывает вопрос учитель, и делает он это осознанно.
    open_for_answers = models.BooleanField(
        "accepts answers online",
        default=True,
        help_text=(
            "Ученик может прислать ответ на этот вопрос. Закрыт — значит "
            "решают на бумаге: ячейка есть, поля ответа нет."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "task"
        verbose_name_plural = "tasks"
        ordering = ("position", "id")

    def __str__(self):
        return self.problem.text[:50] if self.problem_id else f"ячейка {self.position + 1}"


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
        """Проверен тот ответ, за который стоит балл."""
        return self.marks.exists()


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
    Оценка по одной оси: за вопрос работы или за критерий оценивания.

    **Осей две, и они разные.** Вопросы (Q1…Qn) отвечают на «что он решил» —
    у каждого свой максимум, и складываются они в сумму. Критерии (A, B, C, D
    в MYP) отвечают на «как работа оценена» — там уровень 0–8 и выбор по
    лучшему соответствию, а не сумма. Работа может иметь обе оси разом:
    пятнадцать задач с баллами и оценку по критериям A и D.

    Хранятся они одной таблицей с **ровно одним** владельцем — тем же приёмом,
    что у вложения, у которого владельцев три. Причина та же: значение,
    журнал правок и права у них общие, а разошлись бы две таблицы в первой же
    правке.
    """

    student_work = models.ForeignKey(
        StudentWork,
        related_name="marks",
        on_delete=models.CASCADE,
        verbose_name="student's work",
    )
    task = models.ForeignKey(
        Task,
        related_name="marks",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="question",
    )
    criterion = models.ForeignKey(
        Criterion,
        related_name="marks",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="criterion",
    )
    value = models.PositiveSmallIntegerField("value")
    # За какой именно ответ поставлен балл.
    #
    # Пусто у бумажной работы: отправки там нет и не будет, балл просто
    # стоит. У онлайновой ссылка обязательна по смыслу, и держится на ней
    # единственная вещь, которую нельзя потерять: **балл принадлежит тому
    # ответу, за который поставлен**. Ученик прислал новый — старый балл не
    # перевешивается на него молча и не исчезает; он остаётся тем, чем был, а
    # ячейка показывает, что пришло новое и надо посмотреть.
    #
    # Ровно этого опасалось прежнее устройство, где вердикт был полем самой
    # отправки: «отдельная модель добавила бы соблазн перевесить вердикт на
    # новую попытку, чего делать как раз нельзя». Соблазн снимает не место
    # хранения, а эта ссылка.
    #
    # `SET_NULL`: отправку сносит только каскад от задачи или ученика — вместе
    # с самим баллом, — а если она исчезнет иначе, запись учителя должна
    # пережить ответ ученика.
    submission = models.ForeignKey(
        "Submission",
        related_name="marks",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="submission",
        help_text="Ответ, за который поставлен балл. Пусто — работа на бумаге.",
    )

    class Meta:
        verbose_name = "mark"
        verbose_name_plural = "marks"
        ordering = ("criterion__position", "task__position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("student_work", "task"), name="one_mark_per_question"
            ),
            models.UniqueConstraint(
                fields=("student_work", "criterion"), name="one_mark_per_criterion"
            ),
            models.CheckConstraint(
                condition=models.Q(task__isnull=False, criterion__isnull=True)
                | models.Q(task__isnull=True, criterion__isnull=False),
                name="mark_belongs_to_one_axis",
            ),
        ]

    def __str__(self):
        return f"{self.axis}: {self.value}"

    @property
    def axis(self):
        """Ось, по которой поставлена оценка: вопрос или критерий."""
        return self.task or self.criterion


class MarkChange(models.Model):
    """
    Событие правки оценки: кто, когда и на что поменял.

    Оси те же две, что у самой оценки, и по той же причине: исправленная
    отметка — событие, а не новое значение поля, и журнал у обеих осей общий.
    """

    student_work = models.ForeignKey(
        StudentWork,
        related_name="mark_changes",
        on_delete=models.CASCADE,
        verbose_name="student's work",
    )
    task = models.ForeignKey(
        Task,
        related_name="mark_changes",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="question",
    )
    criterion = models.ForeignKey(
        Criterion,
        related_name="mark_changes",
        null=True,
        blank=True,
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
        return f"{self.task or self.criterion}: {self.value}"
class ScanPage(models.Model):
    """
    Одна страница загруженного скана: что на ней прочитано и чья она.

    Строка живёт ровно между загрузкой пачки и её применением, и живёт в базе,
    а не в памяти вкладки, по одной причине: чтение стоит денег. Закрыли
    вкладку, потеряли связь, пришли завтра — прочитанное на месте, и второй раз
    за него никто не платит. По той же причине ключ у страницы — отпечаток
    самой полоски: та же страница, загруженная снова, узнаётся и не
    перечитывается.

    Применение пачки строки уносит: работа сделана, дальше про неё отвечают
    вложения и оценки. Хранить их дольше значило бы держать вторую летопись
    того же самого.
    """

    work = models.ForeignKey(
        Work,
        on_delete=models.CASCADE,
        related_name="scan_pages",
        verbose_name="work",
    )
    index = models.PositiveIntegerField("page number in the upload, from zero")
    fingerprint = models.CharField("sha256 of the strip", max_length=64, blank=True)

    first_name = models.CharField("first name as read", max_length=200, blank=True)
    surname = models.CharField("surname as read", max_length=200, blank=True)
    date_text = models.CharField("date as written", max_length=64, blank=True)
    # Кого модель тут видит из состава курса. Это мнение, а не решение:
    # назначает по нему только человек, и видит он его первым кандидатом.
    guess = models.CharField("model's guess from the roster", max_length=200, blank=True)
    # Шапки на странице нет вовсе. Обычно это лист условий — их раздают перед
    # работой, и они размечают пачку лучше любого почерка: непрерывный ряд
    # таких листов значит «начался следующий ученик». Реже это плохое фото
    # настоящего листа, и тогда это потерянная работа, а не условие; развести
    # их помогает рисунок пачки, а не сама страница.
    headerless = models.BooleanField("no header found on the page", default=False)
    # Наш ли это лист — по коду в углу поля записи. Лист условий печатают из
    # своих материалов, и кода на нём нет; лист решения наш, и код на месте,
    # даже если шапка смазана. Без этого «не наш бланк» и «плохое фото нашего
    # листа» неразличимы, а это очень разные события: первое — норма, второе —
    # потерянная работа ученика.
    ours = models.BooleanField("our blank, by the mark in the corner", default=False)
    # Шестнадцать значений: Q1..Q15 и сумма за страницу. null — пустая клетка.
    cells = models.JSONField("cells as read", default=list, blank=True)
    model = models.CharField("model that read it", max_length=64, blank=True)

    # Кому страница отнесена. Пусто — ещё никому: либо не разобрались, либо
    # разбор до неё не дошёл.
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scan_pages",
        verbose_name="whose page",
    )
    # Человек сказал сам. Такое решение не пересматривается автоматической
    # раскладкой: она предлагает, он решает.
    decided_by_human = models.BooleanField("assigned by a human", default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "scanned page"
        verbose_name_plural = "scanned pages"
        ordering = ("work", "index")
        constraints = [
            models.UniqueConstraint(
                fields=("work", "index"), name="one_row_per_scanned_page"
            )
        ]

    def __str__(self):
        return f"{self.work_id}#{self.index}: {self.first_name} {self.surname}"


class GradingSystem(models.Model):
    """
    Система оценивания: как из работы получается отметка.

    Модель, а не поле, по трём признакам, и все три налицо: у неё есть
    собственное содержимое (полосы), её переиспользуют многие работы, и
    настраивают её один раз.

    **Выбирает её учитель, на каждой работе свою.** Администратор школы не
    выбирает за него: он объявляет, какие системы в школе разрешены, какая
    рекомендована и какая идёт в итог за год. Маленькая проверочная по
    пятибалльной рядом с контрольной по MYP — обычное дело, и это решение
    того, кто ведёт курс.

    Видов несколько, потому что формы у них разные:

    * `points` — сумма баллов за вопросы, полосы в процентах;
    * `levels` — уровни по критериям (MYP): каждый 0–8, отметка получается из
      суммы уровней по опубликованным границам;
    * `passfail` — две полосы;
    * работа **без системы** — законное состояние: баллы есть, отметки нет.
    """

    POINTS = "points"
    LEVELS = "levels"
    PASSFAIL = "passfail"
    KINDS = [
        (POINTS, "sum of question marks, bands in percent"),
        (LEVELS, "levels per criterion, bands on the sum"),
        (PASSFAIL, "pass or fail"),
    ]

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="grading_systems",
        verbose_name="school",
    )
    name = models.CharField("name", max_length=100)
    kind = models.CharField("kind", max_length=16, choices=KINDS, default=POINTS)
    # Наибольший уровень по одному критерию: у MYP это 8. Для `points` не
    # значит ничего.
    top_level = models.PositiveSmallIntegerField("top level per criterion", default=8)
    # Разрешена ли она учителям. Запрет — единственный рычаг администратора
    # над выбором, и он честнее, чем выбирать за учителя.
    is_allowed = models.BooleanField("teachers may choose it", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "grading system"
        verbose_name_plural = "grading systems"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "name"), name="one_grading_system_name_per_school"
            )
        ]

    def __str__(self):
        return self.name


class GradeBand(models.Model):
    """
    Полоса системы: от какого порога какая отметка.

    Пороги у `points` — **в процентах**, а не в баллах: у работ разные
    максимумы, и система, привязанная к абсолютным числам, годится ровно для
    одной работы. У `levels` порог — сумма уровней (у MYP 0–32), и там он
    абсолютный, потому что сумма фиксирована.

    Хранится всегда **балл**, а отметка выводится. Хранить букву значит
    соврать при первой же правке порогов: две работы с одинаковыми баллами
    получили бы разные отметки, и объяснить это было бы некому.
    """

    system = models.ForeignKey(
        GradingSystem,
        on_delete=models.CASCADE,
        related_name="bands",
        verbose_name="system",
    )
    position = models.PositiveIntegerField("position", default=0)
    label = models.CharField("what is shown", max_length=32)
    # Нижняя граница полосы: проценты у `points`, сумма уровней у `levels`.
    threshold = models.PositiveSmallIntegerField("from this value up", default=0)

    class Meta:
        verbose_name = "grade band"
        verbose_name_plural = "grade bands"
        ordering = ("-threshold", "position")

    def __str__(self):
        return f"{self.label} от {self.threshold}"


class Thread(models.Model):
    """
    Разговор о задаче: ученик спрашивает, учитель отвечает.

    **Предмет треда — пара «вопрос работы и ученик».** Тогда он один и тот же и
    на экране задачи, и в будущем чате: чат — просто другой способ читать те же
    треды, сгруппированные по собеседнику, а не вторая переписка о том же.

    Заводится по требованию, как строка журнала: пока никто ничего не спросил,
    треда нет, и «нет вопросов» отличается от «спросили и не ответили» именно
    этим.
    """

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="threads",
        verbose_name="question",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="question_threads",
        verbose_name="student",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "thread"
        verbose_name_plural = "threads"
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("task", "student"), name="one_thread_per_question_and_student"
            )
        ]

    def __str__(self):
        return f"{self.task_id} × {self.student_id}"


class Message(models.Model):
    """
    Одно сообщение в треде.

    У сообщения **автор и адресат**, а не «от ученика / от учителя». Разница
    вылезет в первый же день, когда в разговор войдёт третий — второй учитель,
    методист, родитель, — и схема «две стороны» потребует переделки. Адресат
    может быть пуст: сказанное в тред обращено ко всем, кто его читает.
    """

    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="thread",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="messages_written",
        verbose_name="author",
    )
    to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages_received",
        verbose_name="addressed to",
    )
    text = models.TextField("text")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField("read at", null=True, blank=True)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ("created_at", "id")

    def __str__(self):
        return f"{self.author_id}: {self.text[:40]}"
