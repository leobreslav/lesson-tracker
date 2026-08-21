"""
Банк задач: условия, решения, источники и словарь тегов.

Три вещи, которые надо держать в голове, читая этот файл.

**Условие и решение — разные объекты.** У условия нет метода: «2x²+5x−3=0» это
и разложение на множители, и дискриминант, и выделение полного квадрата. Тема
появляется только вместе с разбором, поэтому теги методов живут на решении, а
у условия свои — про природу задачи.

**Одно условие лежит в нескольких источниках.** Номер — свойство **связи**, а
не задачи: в Мордковиче она №6 в §14, у Сканави — №1123 без раздела. Копий
задачи при этом нет: копии расходятся молча, и через год никто не скажет, в
какой из них верный ответ.

**Три уровня владения** — система, школа, автор; см. `bank/owning.py`.
"""

from config.errors import Codes, api_error
from django.core.exceptions import ValidationError
from django.contrib.postgres.fields import ArrayField
from django.db import models

from .owning import Owned

# --- словарь ---------------------------------------------------------------

SUBJECT = "subject"
OBJECT = "object"
KIND_TASK = "task"
THEOREM = "theorem"
METHOD = "method"

TAG_KINDS = [
    (SUBJECT, "предмет: алгебра, геометрия"),
    (OBJECT, "объект: пирамида, логарифм"),
    (KIND_TASK, "тип задачи: решить, доказать, вычислить"),
    (THEOREM, "теорема: Виета, Пифагора"),
    (METHOD, "метод: разложение на множители, замена переменной"),
]

# Виды, у которых осмысленно «не использует». Отрицать можно только то, чем
# решают: «не использует дискриминант» — да, «не про пирамиду» — нет.
NEGATABLE = {THEOREM, METHOD}

# К чему вид может цепляться. Без этого «пирамида» окажется на решении, а
# «Виета» на условии, и условие темы перестанет что-либо значить.
ON_PROBLEM = {SUBJECT, OBJECT, KIND_TASK}
ON_SOLUTION = {SUBJECT, THEOREM, METHOD}


class Tag(models.Model):
    """
    Слово общего словаря: метод, теорема, объект, тип задачи, предмет.

    **Заводит теги только суперпользователь, и они всегда системные.** Если бы
    каждый вписывал свои, через год были бы «Виет», «т. Виета» и «viete», а
    общий поиск умер бы. Цена закрытого словаря названа честно: учителю нужна
    дверь «предложить тег», иначе он поставит не тот или не поставит никакого.

    Вид задан в коде, а не заводится пользователем: у каждого вида свои
    правила — куда его можно ставить и бывает ли у него отрицание. Вид без
    правил — просто верхняя папка дерева, и отдельным понятием быть не должен.

    Иерархия — **внутри вида**: логарифм внутри функций, Виета внутри теорем о
    корнях. Родитель другого вида — бессмыслица, и она запрещена.
    """

    kind = models.CharField("kind", max_length=16, choices=TAG_KINDS)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="parent tag, same kind",
    )
    name = models.CharField("name", max_length=120)
    position = models.PositiveIntegerField("position", default=0)
    # Тег, который где-то используется, не удаляют, а снимают: удаление
    # оставило бы дыру в чужих сохранённых поисках и темах.
    retired = models.BooleanField("retired", default=False)

    class Meta:
        verbose_name = "tag"
        verbose_name_plural = "tags"
        ordering = ("kind", "position", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "name"), name="one_tag_name_per_kind"
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.parent and self.parent.kind != self.kind:
            raise ValidationError(
                {"parent": "Родитель тега должен быть того же вида."}
            )
        if self.parent_id == self.pk and self.pk:
            raise ValidationError({"parent": "Тег не может быть родителем себе."})


# --- условия и решения -----------------------------------------------------


class Family(models.Model):
    """
    Семья аналогов: те же задачи с другими числами.

    Аналогичность **симметрична и транзитивна** — если A аналог B, а B аналог
    C, то A аналог C, и главного среди них нет. Пары ссылок этого не выражают:
    пришлось бы считать транзитивное замыкание при каждом показе, а удаление
    одной задачи рвало бы семью на куски.

    Поэтому — объект, а у задачи одно необязательное поле на него. «Показать
    аналоги» становится одним запросом, слияние двух семей — правкой поля у
    нескольких строк.

    Семью **не упорядочивают и главного не назначают**: две задачи могли быть
    написаны независимо, и никто из них не первый. А если нужен исходник, на
    это отвечает другое поле — «произошла от».
    """

    name = models.CharField("name", max_length=200, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="who declared it",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "family of analogues"
        verbose_name_plural = "families of analogues"

    def __str__(self):
        return self.name or f"семья {self.pk}"


class Problem(Owned):
    """
    Условие задачи: то, что увидит ученик.

    Живёт само по себе — без источника (учитель придумал), без решений (никто
    не написал разбор) и без тегов. Всё это связи, а не части.
    """

    text = models.TextField("statement, Markdown with LaTeX")
    # Что считается верным ответом — свойство **условия**, а не работы, в
    # которой его спросили: «x+3» и «3+x» одинаково верны везде. Список, а не
    # строка, ровно поэтому: форм у верного ответа несколько.
    answers = ArrayField(
        models.TextField(),
        default=list,
        blank=True,
        verbose_name="accepted answers",
        help_text="Хранятся ровно как введены: обработка — при сравнении.",
    )

    family = models.ForeignKey(
        Family,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
        verbose_name="family of analogues",
    )
    # Откуда взялась. Факт, а не смысл: после правки копия может стать
    # совершенно другой задачей, и выдавать это за аналогичность нельзя.
    copied_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="copies",
        verbose_name="copied from",
    )
    retired = models.BooleanField("retired", default=False)
    tags = models.ManyToManyField(
        Tag, through="ProblemTag", related_name="problems", blank=True
    )

    class Meta:
        verbose_name = "problem"
        verbose_name_plural = "problems"
        ordering = ("-created_at", "id")

    def __str__(self):
        return self.text[:60]


class Solution(Owned):
    """
    Разбор одного условия. Их бывает несколько, и это главное.

    Решение принадлежит **одному** условию — иначе «решение чего это»
    перестаёт иметь ответ. А владельцы у них независимые: личное решение к
    системному условию это главный способ, которым учитель вкладывается в
    общую библиотеку.
    """

    problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        related_name="solutions",
        verbose_name="problem",
    )
    title = models.CharField("short name of the method", max_length=200, blank=True)
    text = models.TextField("the solution itself, Markdown with LaTeX")
    retired = models.BooleanField("retired", default=False)
    tags = models.ManyToManyField(
        Tag, through="SolutionTag", related_name="solutions", blank=True
    )

    class Meta:
        verbose_name = "solution"
        verbose_name_plural = "solutions"
        ordering = ("problem", "id")

    def __str__(self):
        return self.title or self.text[:60]


class ProblemTag(models.Model):
    """
    Тег на условии: про природу задачи, а не про метод.

    Отрицания тут нет вовсе: у условия нет метода, значит и отрицать нечего.
    """

    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="links")
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "tag on a problem"
        verbose_name_plural = "tags on problems"
        constraints = [
            models.UniqueConstraint(
                fields=("problem", "tag"), name="one_tag_per_problem"
            )
        ]

    def clean(self):
        if self.tag.kind not in ON_PROBLEM:
            raise ValidationError({"tag": "Тег этого вида ставится на решение."})


class SolutionTag(models.Model):
    """
    Тег на решении, **со знаком**.

    «Не использует дискриминант» — утверждение, проверенное человеком;
    отсутствие тега значит «неизвестно». Это разные вещи, и хранить их одним
    нельзя: именно на отрицании держится поиск «решение без дискриминанта»,
    ради которого всё и затевалось.
    """

    USES = "uses"
    AVOIDS = "avoids"
    SIDES = [(USES, "использует"), (AVOIDS, "намеренно обходится")]

    solution = models.ForeignKey(Solution, on_delete=models.CASCADE, related_name="links")
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="+")
    side = models.CharField("side", max_length=8, choices=SIDES, default=USES)

    class Meta:
        verbose_name = "tag on a solution"
        verbose_name_plural = "tags on solutions"
        constraints = [
            models.UniqueConstraint(
                fields=("solution", "tag"), name="one_tag_per_solution"
            )
        ]

    def clean(self):
        if self.tag.kind not in ON_SOLUTION:
            raise ValidationError({"tag": "Тег этого вида ставится на условие."})
        if self.side == self.AVOIDS and self.tag.kind not in NEGATABLE:
            raise ValidationError(
                {"side": "Отрицать можно только метод или теорему."}
            )


# --- источники -------------------------------------------------------------


class Source(Owned):
    """
    Источник: как правило книга. Жёсткий каталог системы.

    Отдельного системного жёсткого каталога заводить не нужно — **книга и есть
    он**, с разделами вместо подпапок и номерами вместо порядка.
    """

    title = models.CharField("title", max_length=300)
    author = models.CharField("author", max_length=200, blank=True)
    note = models.TextField("note", blank=True)

    class Meta:
        verbose_name = "source"
        verbose_name_plural = "sources"
        ordering = ("title",)

    def __str__(self):
        return self.title


class Section(models.Model):
    """
    Раздел книги. Глубина **любая**, и это не противоречит двухуровневому плану.

    Разница по существу: план мы проектируем — и там глубина наш выбор, за
    который платит вёрстка и перетаскивание. Оглавление книги мы
    **переписываем**: там бывает 1.2.3, и запретить это значит заставить
    учителя врать при вводе.

    Цена ограничена тем, что структура не правится мышью: ссылка на родителя,
    отступ на экране, хлебные крошки в шапке — ни сортировки перетаскиванием,
    ни правил «что куда можно класть».
    """

    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="sections"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    title = models.CharField("title", max_length=300)
    position = models.PositiveIntegerField("position", default=0)

    class Meta:
        verbose_name = "section"
        verbose_name_plural = "sections"
        ordering = ("position", "id")

    def __str__(self):
        return self.title


class Entry(models.Model):
    """
    Задача в источнике: номер, страница, место.

    Номер — **строка**, а не число: бывает «14а» и «II.3». Порядок задаётся
    отдельным полем, потому что по строке он не выводится.
    """

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="entries")
    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    problem = models.ForeignKey(
        Problem, on_delete=models.CASCADE, related_name="entries"
    )
    label = models.CharField("number as printed", max_length=32, blank=True)
    page = models.PositiveIntegerField("page", null=True, blank=True)
    position = models.PositiveIntegerField("position", default=0)

    class Meta:
        verbose_name = "problem in a source"
        verbose_name_plural = "problems in sources"
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("source", "problem", "label"),
                name="one_place_per_problem_in_a_source",
            )
        ]

    def __str__(self):
        return f"{self.source_id} №{self.label}"


class SavedSearch(Owned):
    """
    Названный запрос: выражение, которое сохранили, чтобы вернуться.

    Хранится **дерево**, а не список найденных задач: банк пополняется, и
    смысл сохранённого поиска ровно в том, что завтра он найдёт больше. Список
    задач — это папка, и она в системе есть отдельно.

    Уровни владения те же, что у книг: системный запрос — тот, что предлагают
    всем; школьный собирает завуч; личный человек правит сам. Никакого нового
    правила видимости тут нет, и это главное, ради чего `Owned` заведён.
    """

    name = models.CharField("name", max_length=200)
    expression = models.JSONField("expression tree", default=dict)

    class Meta:
        verbose_name = "saved search"
        verbose_name_plural = "saved searches"
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class Introduction(models.Model):
    """
    «Этот урок вводит этот тег» — план как хронология появления понятий.

    Роль одна и только одна: **вводит**. Обсуждались и другие («повторяет»,
    «использует»), и все они отпали по одной причине: отвечают они на разные
    вопросы, а нужен ровно один — «что к этому дню уже пройдено». Повторение на
    него не влияет, а использование выводится из решений, которые уже
    размечены тегами.

    Уникальность — на **курс и тег**, а не на урок: понятие вводится однажды.
    Вписали его второму уроку — значит первое место было ошибкой, и его надо
    перенести, а не завести рядом ещё одно.
    """

    course = models.ForeignKey(
        "schedule.Course",
        on_delete=models.CASCADE,
        related_name="introductions",
        verbose_name="course",
    )
    node = models.ForeignKey(
        "plans.PlanNode",
        on_delete=models.CASCADE,
        related_name="introductions",
        verbose_name="the lesson that introduces it",
    )
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="introductions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tag introduced by a lesson"
        verbose_name_plural = "tags introduced by lessons"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "tag"), name="one_lesson_introduces_a_tag"
            )
        ]

    def __str__(self):
        return f"{self.node} вводит {self.tag}"


class Topic(models.Model):
    """
    Тема — **папка, заданная условием**, а не списком.

    Жёсткий каталог у нас уже есть: это источники, где задача лежит по адресу
    «книга, раздел, номер». Тематический устроен иначе: «квадратные уравнения»
    — это все разборы, которые пользуются такими-то средствами, и список у них
    пополняется сам, когда кто-то напишет новый разбор.

    Живёт тема **только системной**: тематический каталог общий, и школьная
    копия «Квадратных уравнений» рядом с системной означала бы, что тема — это
    два разных ответа на один вопрос. Личные подборки выражаются другим —
    сохранённым поиском (свой, с именем) и своей книгой (жёсткая папка).

    Условие тут не общее логическое дерево, а три поля, и это сознательное
    сужение: тема должна читаться названием своих тегов, а не разбором скобок.
    """

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="parent topic",
    )
    title = models.CharField("title", max_length=200)
    position = models.PositiveIntegerField("position", default=0)

    # Суть: чем разбор обязан пользоваться. Все сразу — «и», потому что тема
    # это пересечение средств, а не их список.
    essence = models.ManyToManyField(
        Tag, related_name="topics_needing", blank=True, verbose_name="must use"
    )
    # Чего в разборе быть не должно: «без производной» — обычное требование к
    # теме, идущей до производной.
    forbidden = models.ManyToManyField(
        Tag, related_name="topics_avoiding", blank=True, verbose_name="must avoid"
    )
    # Закрытая тема требует, чтобы разбор не выходил за пройденное вовсе.
    closed = models.BooleanField("closed to what has been covered", default=False)

    class Meta:
        verbose_name = "topic"
        verbose_name_plural = "topics"
        ordering = ("position", "title", "id")

    def __str__(self):
        return self.title
