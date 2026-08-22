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
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from .owning import SCHOOL, Owned

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

    **Задача бывает составной**, и тогда она дерево ровно из двух уровней:

        сюжет: «Дан треугольник ABC со сторонами 3, 4, 5»
          ├── пункт: «Найдите площадь»
          └── пункт: «Найдите радиус вписанной окружности»

    Это дерево — про **смысл**, а не про то, как задачу напечатали: пункт
    читается только вместе со своим сюжетом, и в любой книге, которая его
    перепечатает, треугольник будет тот же. Поэтому ни номеров, ни букв здесь
    нет — они свойство встречи с книгой и живут на `Entry`. Один и тот же пункт
    у Мордковича «3а», а у Галицкого «5б», и обе метки правдивы.

    **Задача — это лист.** Сюжет не задача: у него нет ни вопроса, ни ответа,
    ни балла. Из поиска он исключается, ячейкой работы не бывает, и оценивают
    всегда пункт. Отсюда правило, которое стоит помнить при любой выборке:
    «все задачи» — это `leaves()`, а не `Problem.objects.all()`.

    **Родитель заводится только у зависимого пункта.** Четыре несвязанных
    уравнения, напечатанных под одним номером буквами а–г, — это четыре
    самостоятельные задачи, а их «пунктовость» целиком свойство книги (см.
    `Entry`). Проверить это машиной нельзя, и она не проверяет: решает
    вписывающий, а различие видно глазами — есть ли в сюжете данные, без
    которых пункт бессмыслен.

    Глубина ровно два, и это тот же размен, что в учебном плане: «1 а) i)»
    выражается меткой пункта или плоским списком, а третий уровень был бы
    механизмом ради оформления.
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
    # Сюжет, если это его пункт. `CASCADE`: пункт без сюжета бессмыслен, а
    # снос сюжета, чьи пункты уже спрошены, упрётся в `PROTECT` у ячейки
    # работы — то есть не случится вовсе.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="parts",
        verbose_name="the stem this is a question to",
    )
    # Порядок пунктов **у автора**. По метке он не выводится: «а, б, в»
    # пропускает «ё» и «й», римские идут не по алфавиту, а бывают и звёздочки.
    # Порядок в книге — своё поле у `Entry`, и они законно разные.
    position = models.PositiveIntegerField("position among the parts", default=0)

    class Meta:
        verbose_name = "problem"
        verbose_name_plural = "problems"
        ordering = ("-created_at", "id")

    def __str__(self):
        return self.text[:60] or f"сюжет {self.pk}"

    @property
    def is_part(self) -> bool:
        return self.parent_id is not None

    def clean(self):
        if self.parent_id and self.parent.parent_id:
            raise ValidationError(
                {"parent": "Пункт пункта не бывает: дерево задачи ровно двухуровневое."}
            )
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({"parent": "Задача не может быть пунктом самой себя."})


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
    # Предмет книги — тег из общего словаря, а не своё поле и не школьный
    # `schedule.Subject`: банк общий на все школы, а тот справочник у каждой
    # свой. Предмет книги достаётся её задачам при вписывании — иначе самый
    # частый фильтр не работал бы ровно там, где задач больше всего.
    subject = models.ForeignKey(
        Tag,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sources",
        verbose_name="subject",
    )

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
    Строка книги: адрес, по которому задача в ней напечатана.

    Это **второе дерево** банка, и путать его с деревом задачи нельзя, хотя
    выглядят они похоже:

        дерево задачи   — про смысл, одно на все книги (`Problem.parent`)
        дерево книги    — про адрес, своё в каждой книге (`Entry.parent`)

    Пример, ради которого разделение и заведено. Один и тот же пункт:

        Мордкович · §14
          └── «3»   → сюжет «Дан треугольник ABC…»
               ├── «3а» → пункт «Найдите площадь»
               └── «3б» → пункт «Найдите радиус»

        Галицкий · Глава 2
          └── «5»
               ├── «5а» → (другой пункт)
               └── «5б» → **тот же** пункт «Найдите площадь»

    Метка и порядок принадлежат строке, поэтому «3а» и «5б» спокойно живут
    рядом, показывая на одно условие. Держать букву на самой задаче было
    нельзя ровно поэтому: она вместила бы только одну.

    **Строка может ни на что не показывать** (`problem=None`) — это чистый
    номер, у которого есть только пункты: «15. а) x²=4 б) x²=9», где над
    буквами не напечатано ничего. Если же над ними напечатано условие, оно
    заводится сюжетом-задачей, и строка-номер показывает на него.

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
        Problem,
        on_delete=models.CASCADE,
        related_name="entries",
        null=True,
        blank=True,
        verbose_name="what stands here; empty means a bare number",
    )
    # Строка-номер, если это строка-пункт. `CASCADE`: пункт без своего номера
    # адресом не является.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="the numbered row this one is a part of",
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

    def clean(self):
        if self.parent_id and self.parent.parent_id:
            raise ValidationError(
                {"parent": "Строка книги вложена ровно на один уровень: номер и пункт."}
            )


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


class Topic(Owned):
    """
    Тема — **папка, заданная условием**, и она же сохранённый поиск.

    Структурно это одно и то же: названное условие с местом в дереве и
    владением. Держать две вещи ради разницы «общая и выверенная» против
    «моя и на бегу» значило бы иметь два компилятора выражений, два редактора и
    два набора прав — а различие выражается уровнем владения, который у нас уже
    есть.

    **Вложение — это сужение**, а не просто место: условие темы складывается с
    условиями всех её родителей по «и». Иначе дерево врёт: «Квадратные
    уравнения ▸ Через Виета», в котором лежат задачи, которых нет в родителе,
    читается как ошибка. Отсюда и то, что внутри «Квадратных уравнений» тема
    называется просто «через Виета» и несёт один тег: каждый уровень говорит
    только то, что добавляет.

    Пустое условие законно — это «просто раздел», рубрика ради структуры; на
    верхнем уровне оно значит «все задачи».
    """

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="parent topic",
    )
    title = models.CharField("title", max_length=200)
    position = models.PositiveIntegerField("position", default=0)
    expression = models.JSONField("condition", default=dict, blank=True)

    class Meta:
        verbose_name = "topic"
        verbose_name_plural = "topics"
        ordering = ("position", "title", "id")

    def __str__(self):
        return self.title

    def chain(self) -> list:
        """Сама тема и все её родители — от корня вниз."""
        found = []
        node = self
        while node is not None:
            found.append(node)
            node = node.parent
        return list(reversed(found))

    def condition(self) -> dict:
        """
        Условие целиком: своё вместе с родительскими.

        Родительское **не хранится** в ребёнке — считается обходом вверх.
        Хранить значило бы держать копию, которая разъедется с оригиналом при
        первой же правке.
        """
        parts = [topic.expression for topic in self.chain() if topic.expression]
        if not parts:
            return {}
        return parts[0] if len(parts) == 1 else {"all": parts}



class Proposal(models.Model):
    """
    Предложение: что пользователь говорит тем, кто вправе править.

    Общий каталог и словарь тегов закрыты намеренно — иначе через год в них
    будет «Виет», «т. Виета» и «viete», — но у закрытости есть цена: учитель,
    нашедший опечатку в системной задаче или знающий недостающий тег, не может
    сделать **ничего**. Единственным путём оставалась копия, то есть дубль в
    общем каталоге. Эта модель и есть недостающая дверь.

    **Кому идёт предложение, не хранится, а выводится** — из владения того, о
    чём речь: системное разбирает суперпользователь, школьное —
    администраторы школы. Поле «адресат» было бы вторым источником правды о
    том же самом и разошлось бы с владением в первый же переезд задачи между
    уровнями.

    Виды не выдуманы, а взяты из того, с чем приходят:

    | вид | о чём | что делает принятие |
    |-----|-------|---------------------|
    | `typo` | опечатка в условии или разборе | вписывает предложенный текст |
    | `tag` | «сюда просится такой-то тег» | вешает тег; новый — заводит |
    | `problem` | «вот вам задача» | заводит условие на том уровне |
    | `solution` | «вот разбор к этой задаче» | заводит разбор |
    | `other` | всё остальное | ничего, кроме пометки |

    Принятие **делает дело**, а не просто помечает: предложение, после
    которого администратору надо ещё раз сделать то же самое руками, никто не
    станет ни писать, ни разбирать.
    """

    TYPO = "typo"
    TAG = "tag"
    PROBLEM = "problem"
    SOLUTION = "solution"
    OTHER = "other"
    KINDS = [
        (TYPO, "опечатка"),
        (TAG, "тег"),
        (PROBLEM, "задача"),
        (SOLUTION, "разбор"),
        (OTHER, "прочее"),
    ]

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    STATES = [
        (PENDING, "ждёт"),
        (ACCEPTED, "принято"),
        (DECLINED, "отклонено"),
    ]

    kind = models.CharField("kind", max_length=16, choices=KINDS)
    # О чём речь. Целей три вида, и они **не исключают друг друга**: «повесить
    # такой-то тег на эту задачу» называет и задачу, и тег.
    problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposals",
    )
    solution = models.ForeignKey(
        Solution,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposals",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name="the tag being suggested, if it already exists",
    )

    # Куда адресовано: в общий каталог или своей школе. У предложения про
    # существующий объект считается из его владения, у новой задачи — выбор
    # автора.
    level = models.CharField("level", max_length=16, default=SCHOOL)
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )

    text = models.TextField("what the person says", blank=True)
    # Предлагаемое: исправленный текст, условие новой задачи, разбор, имя
    # нового тега. Одно поле на все виды намеренно — это всегда «вот что я
    # предлагаю написать», и разводить его по видам значило бы завести пять
    # полей, из которых четыре всегда пусты.
    suggested = models.TextField("the text being suggested", blank=True)

    state = models.CharField("state", max_length=16, choices=STATES, default=PENDING)
    answer = models.TextField("what the resolver said", blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="proposals",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "proposal"
        verbose_name_plural = "proposals"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.get_kind_display()}: {self.text[:40]}"


class ProposalNote(models.Model):
    """
    Реплика в разговоре о предложении.

    Разговор нужен потому, что половина предложений — не «да/нет», а «а что
    именно не так?»: опечатку надо показать, тег обсудить, задачу уточнить.
    Отказ без разговора превращается в загадку, а с ним — в решение.

    Своя модель, а не `works.Message`: тот привязан к паре «задача и ученик» и
    отвечает на другой вопрос. Общий разговор поверх обоих — отдельная работа,
    и делать её заодно значит переделывать оба.
    """

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    text = models.TextField("reply")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "note on a proposal"
        verbose_name_plural = "notes on proposals"
        ordering = ("created_at", "id")

    def __str__(self):
        return self.text[:40]
