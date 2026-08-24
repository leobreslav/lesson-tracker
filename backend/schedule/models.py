from collections import defaultdict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import services

# уроков в дне: больше десятого номера в школьном расписании не бывает
MAX_LESSON_NUMBER = 10

# Год обучения считается от первого класса и сверху ничем не ограничен:
# в британской школе их тринадцать, в IB-школе столько же, а где-то
# считают и иначе. Верхняя граница была бы догадкой о чужой системе, и
# сравнивать её здесь всё равно не с чем — сортировка работает на любом
# числе.
MIN_GRADE = 1


class Subject(models.Model):
    """
    A subject of the school: «Алгебра», «Геометрия».

    Until now the subject lived inside the course name and could not be
    searched on. The library needs it as a field — a plan is looked for by
    subject and grade, not by the label «9Б Алгебра» somebody typed.

    The list belongs to the school: two schools name their subjects
    differently and neither should see the other's spelling.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="subjects",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    name = models.CharField("name", max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "subject"
        verbose_name_plural = "subjects"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "name"), name="unique_subject_name_per_school"
            ),
        ]

    def __str__(self):
        return self.name


class GradeLevel(models.Model):
    """
    A year group as this school writes it: «Grade 6», «MYP 4», «10 класс».

    Two fields on purpose. `level` is the year of study counted from the
    first one and is what sorting and comparison run on; `name` is what the
    school puts on the door. Schools using several systems at once — MYP
    alongside ordinary numbers — would otherwise sort «MYP 4» next to the
    fourth grade instead of the ninth.

    The list belongs to the school, like the subjects next to it.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="grade_levels",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    level = models.PositiveSmallIntegerField(
        "year of study",
        validators=[MinValueValidator(MIN_GRADE)],
        help_text=(
            "The year of study counted from the first one, not the number "
            "inside the name. «MYP 4» is the ninth year of study, so its "
            "level is 9 — that is what keeps sorting right in a school that "
            "uses both systems."
        ),
    )
    name = models.CharField(
        "name",
        max_length=50,
        help_text="What the school calls it: «Grade 6», «MYP 4», «10 класс».",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "grade level"
        verbose_name_plural = "grade levels"
        ordering = ("level",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "level"), name="unique_grade_level_per_school"
            ),
        ]

    def __str__(self):
        return self.name


class CourseQuerySet(models.QuerySet):
    def for_teacher(self, user):
        """
        Курсы учителя — это курсы, на которые его назначили. И только.

        Условие было длиннее: назначенные **плюс** те, где у него уже есть
        уроки или строки плана. Вторая половина защищала от того, что
        снятие назначения спрячет от человека его собственную работу. Теперь
        прятать нечего: план, работы и расписание принадлежат курсу, личного
        внутри курса не осталось вовсе, и «моё» ровно совпадает с «мне его
        поручили».

        Отсюда и цена, названная прямо: у кого сняли назначение, тот курса
        больше не видит. Работа при этом цела и достаётся следующему
        ведущему целиком — ради этого всё и переносилось.
        """
        if user is None or not user.is_authenticated or user.school_id is None:
            return self.none()

        return self.filter(assignments__teacher=user, school_id=user.school_id)

    def writable_by(self, user):
        """
        Курсы, содержимое которых человек вправе править.

        Ведущему — его собственные, администратору школы — все её курсы.
        Расписание и журнал занятия так работали всегда
        (`IsCourseTeacherOrSchoolAdmin`, `may_write`), а план и работы
        оставались закрытыми, и это была не принципиальная разница, а
        незакрытая непоследовательность: две трети курса администратор уже
        чинил, а треть — нет.

        **Это не то же самое, что «мои курсы».** `for_teacher` отвечает на
        вопрос «что показывать по умолчанию», и расширять его нельзя: у
        завуча, который сам ведёт два курса, селектор в учебном плане
        показал бы девятнадцать. Право и принадлежность — разные вопросы, и
        разъезжаются они сразу же, стоит их слить.
        """
        if user is None or not user.is_authenticated or user.school_id is None:
            return self.none()

        if user.is_school_admin and not user.is_student:
            return self.filter(school_id=user.school_id)

        return self.for_teacher(user)

    def for_student(self, user, *, active_only=True):
        """
        Курсы ученика. Два вопроса одной функцией — и это не удобство.

        «Можно работать» и «можно видеть своё» — разные права: снятый с
        курса продолжает читать сделанное, но ничего в нём не делает. Пока
        оба ответа даёт одно место, разойтись им негде; разложенные по
        queryset'ам, они разойдутся в первом же забытом фильтре — с
        учительскими выборками это уже происходило.

        **Оба условия стоят в одном `filter`, и это не оформление.** Зачисление
        — связь «многие ко многим», и второй вызов `filter` по той же связи
        Django заводит **вторым join'ом**: «курс, где есть строка этого
        ученика, и где есть какая-нибудь строка без даты снятия». В курсе с
        одним учеником это неотличимо от нужного, а в курсе с тридцатью —
        всегда истина: строка соседа и есть та, что без даты. То есть снятый
        с курса оставался бы действующим ровно там, где ошибка стоит дороже
        всего, — в настоящем классе.

        Пойман он был не здесь: снятый ученик, у которого в курсе есть
        одноклассник, спокойно присылал фотографию работы. Отсюда и тест с
        одноклассником — без него подделка выглядит рабочей.
        """
        if user is None or not user.is_authenticated or user.school_id is None:
            return self.none()

        mine = {"students__student": user}
        if active_only:
            mine["students__removed_at__isnull"] = True

        return self.filter(school_id=user.school_id, **mine).distinct()


class Course(models.Model):
    """
    What somebody teaches: a group and a subject together, «9B Algebra».

    The course belongs to the school and is created by its administrators —
    a teacher picks from the list rather than inventing their own entry, or
    two colleagues teaching the same group would end up with two courses
    nobody can compare.

    The link to a year is deliberate: next year 9B becomes 10B, and that is a
    different course with its own load.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="courses",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    # deleting a year takes its courses with it; lesson slots and plan rows
    # hang off the course under PROTECT, so a course in use cannot vanish
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="courses",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    # the subject and the grade are what the library searches on; the name
    # keeps the letter and any local wording («9Б», «9Б углублённая»)
    subject = models.ForeignKey(
        Subject,
        related_name="courses",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="subject",
    )
    grade = models.ForeignKey(
        GradeLevel,
        related_name="courses",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="grade level",
    )
    # as long as a subject name: the label carries a letter and whatever
    # clarification the school needs («9Б», «10 класс, группа B»), and a limit
    # that fits «9Б» tells the school how to name its courses
    name = models.CharField("name", max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CourseQuerySet.as_manager()

    class Meta:
        verbose_name = "course"
        verbose_name_plural = "courses"
        # by year of study first: «MYP 4» and «9 класс» are the same year and
        # belong next to each other, whatever they are called
        ordering = ("grade__level", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("school", "year", "name"), name="unique_course_name_per_year"
            ),
        ]

    def __str__(self):
        return self.name


class CourseMethodist(models.Model):
    """
    Кто утверждает план этого курса.

    Полномочие, а не ступень иерархии: методист — такой же учитель, просто
    ему присылают план на утверждение. Висит на **курсе**, а не на предмете:
    предмет школы это ярлык, а отвечают за конкретный курс — «9Б Алгебра», —
    и назначают методиста там же, где раздают сам курс.

    Устроено как `CourseAssignment` рядом: та же пара «курс и человек», та
    же уникальность, тот же администратор, который её ставит. Разница в
    вопросе: одна строка отвечает «кто ведёт», другая — «кто утверждает», и
    у одного курса это обычно разные люди.
    """

    course = models.ForeignKey(
        Course,
        related_name="methodists",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="methodist_of",
        on_delete=models.CASCADE,
        verbose_name="methodist",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="methodists_assigned",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="assigned by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "course methodist"
        verbose_name_plural = "course methodists"
        ordering = ("course__name", "user__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "user"), name="one_methodist_row_per_course"
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.course}"


class CourseStudent(models.Model):
    """
    Кто учится на этом курсе.

    Третья таблица той же формы, что `CourseAssignment` и `CourseMethodist`
    рядом: пара «курс и человек», уникальная, ставит её администратор. И тот
    же принцип — курс общий, а привязка к нему личная.

    Разница одна, и она важная: **строка не удаляется**. Снятый с курса
    ученик перестаёт в нём работать, но продолжает видеть, что уже сделал:
    его ответы и результаты никуда не делись, и право их читать — это и есть
    строка. Поэтому снятие ставит `removed_at`, а возврат его снимает; пара
    остаётся одна и та же, второй строки не заводится.

    Отсюда два разных вопроса, и оба задаются часто:

    * **можно ли работать в курсе** — строка есть и `removed_at` пуст;
    * **можно ли видеть своё в курсе** — строка есть, любая.

    Оба ответа даёт менеджер курсов (`Course.objects.for_student`), чтобы
    они не разъехались по queryset'ам, как это уже случалось с учителями.

    Истории приходов и уходов нет намеренно: она никому не понадобилась, а у
    ответов будут собственные метки времени.
    """

    course = models.ForeignKey(
        Course,
        related_name="students",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="enrolments",
        on_delete=models.CASCADE,
        verbose_name="student",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="students_enrolled",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="enrolled by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(
        "removed at",
        null=True,
        blank=True,
        help_text="Снят с курса: работать нельзя, своё прошлое видно.",
    )

    class Meta:
        verbose_name = "course student"
        verbose_name_plural = "course students"
        ordering = ("course__name", "student__last_name", "student__email")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "student"), name="one_enrolment_row_per_course"
            ),
        ]
        indexes = [
            models.Index(fields=("student", "removed_at"), name="active_enrolment_idx"),
        ]

    def __str__(self):
        return f"{self.student} — {self.course}"

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class Homegroup(models.Model):
    """
    Класс: устойчивое множество учеников, у которого есть имя. «6А», «DP1».

    Слово «класс» в этом проекте уже занято дважды — параллелью
    (`GradeLevel`, год обучения) и курсом («9Б Алгебра»), — и третье значение
    ему бы не пережить, поэтому в коде он `Homegroup`. В интерфейсе он
    называется так, как называет школа.

    **Чем он не является — важнее того, чем является.** Он не курс: на
    курсе учатся ради предмета, а в классе просто числятся. Он и не
    параллель: в шестой параллели два класса, 6А и 6Б, и учатся они то
    вместе, то вперемешку, разбившись на подгруппы. Собственно, ради этого
    «то вместе, то вперемешку» он и заведён.

    **Связи с курсом у него нет и не будет.** Курс класса — это множество
    классов его учеников, и выводится оно из зачислений. Записанная связь
    была бы вторым ответом на вопрос, на который уже отвечают ученики, и
    разошлась бы с ними молча: «курс 6А», в котором семеро из 6А и трое из
    6Б, — обычное дело, а в базе стояло бы «6А». В школе с выбором предметов
    (DP) связи не существует вовсе: там каждый курс собран из кусков разных
    классов, и правильного единственного ответа нет.

    Цена этого решения названа прямо: **пока учеников не зачислили, класса у
    курса нет**. Расписание рисуют в августе, а зачисляют в сентябре, и всё
    это время дневной вид «по классам» покажет такие часы в крайнем столбце
    «не указан». Спрятать их было бы хуже: пропавший с экрана урок не
    находят месяцами.

    Классный руководитель — необязательная ссылка на человека, а не роль в
    правах: он ничего не открывает и ничего не закрывает. Это ответ на
    вопрос «чей это класс», который задают, когда нужно кому-то написать.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="homegroups",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    # год обязателен по тому же доводу, что у курса: в следующем году 6А
    # становится 7А, и это другая строка, а не переименованная эта
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="homegroups",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    grade = models.ForeignKey(
        GradeLevel,
        related_name="homegroups",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="grade level",
    )
    name = models.CharField("name", max_length=100)
    # классный руководитель: свойство класса, а не право в системе
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="homegroups_led",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="tutor",
        help_text="Классный руководитель: кому писать про этот класс.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "homegroup"
        verbose_name_plural = "homegroups"
        ordering = ("grade__level", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("school", "year", "name"),
                name="unique_homegroup_name_per_year",
            ),
        ]

    def __str__(self):
        return self.name


class HomegroupStudent(models.Model):
    """
    Кто в этом классе. Строка со снятием, как зачисление на курс.

    Не удаляется по той же причине: перевод из 6А в 6Б посреди года не
    должен стирать, что человек был в 6А, — расписание сентября собиралось
    по тому составу, и переписывать его задним числом нельзя.

    **Класс на год у ученика один**, и это ограничение базы, а не
    договорённость. Частичное — только среди незакрытых строк: иначе перевод
    был бы невозможен вовсе, потому что старая строка держала бы место.

    Год ради этого лежит **на самой строке**, хотя он же есть у класса, и
    это единственная денормализация в этой паре таблиц. Причина
    техническая и названа прямо: ограничение уникальности в Postgres
    считается по колонкам одной таблицы, а `homegroup__year` — колонка
    соседней; Django на такое отвечает `models.E012`. Выбор был между копией
    поля и правилом, живущим только в коде, — а правило, живущее только в
    коде, здесь уже обходили дважды (сначала импортом, потом админкой).

    Копия при этом не может разойтись с оригиналом: она проставляется в
    `save()` из класса и нигде больше не пишется, а сторож
    (`HomegroupYearMatchesTests`) проверяет, что не разошлась.
    """

    homegroup = models.ForeignKey(
        Homegroup,
        related_name="students",
        on_delete=models.CASCADE,
        verbose_name="homegroup",
    )
    # копия года класса — ради ограничения уникальности, см. докстринг.
    # Пишется только в `save()`, руками не заполняется никогда
    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="homegroup_rows",
        on_delete=models.CASCADE,
        editable=False,
        verbose_name="school year",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="homegroups",
        on_delete=models.CASCADE,
        verbose_name="student",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="homegroup_rows_added",
        null=True,
        on_delete=models.SET_NULL,
        verbose_name="added by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField("removed at", null=True, blank=True)

    class Meta:
        verbose_name = "homegroup student"
        verbose_name_plural = "homegroup students"
        ordering = ("homegroup__name", "student__last_name", "student__email")
        constraints = [
            models.UniqueConstraint(
                fields=("homegroup", "student"),
                name="one_homegroup_row_per_student",
            ),
            models.UniqueConstraint(
                fields=("student", "year"),
                condition=models.Q(removed_at__isnull=True),
                name="one_active_homegroup_per_year",
                violation_error_message=(
                    "This student already belongs to a homegroup this year."
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=("student", "removed_at"), name="active_homegroup_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        """Год берётся у класса — и только у него: второй источник тут не нужен."""
        if self.homegroup_id:
            self.year_id = self.homegroup.year_id
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} — {self.homegroup}"

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class Room(models.Model):
    """
    Кабинет школы: где идёт занятие.

    Четвёртый справочник рядом с предметами, параллелями и звонками, и
    заведён он тем же порядком: список принадлежит школе, ведёт его
    администратор, учитель из него выбирает. Имя — человеческое поле, как у
    курса: «214», «Актовый зал», «Лаборатория химии» — что школа пишет на
    двери, то и лежит здесь.

    **Делимый кабинет — не разрешение, а свойство помещения.** Занятость
    кабинета в этой школе никогда не запрет: два класса, загнанных в один
    кабинет, — обычное дело, и отказ на этом месте просто заставил бы врать
    расписанию. Значит остаётся предупреждение, а у него единственная беда —
    привыкание: горящий каждый день спортзал перестают читать через неделю,
    а вместе с ним перестают читать и настоящие. Поэтому у зала, где
    несколько занятий разом — норма, флаг стоит, и про него молчат.

    Архивный кабинет — закрытый на ремонт или отданный под склад: из
    выбора он исчезает, а история остаётся. Удалять его ради этого нельзя:
    часы прошедших уроков ссылаются на него `PROTECT`'ом, и это правильно —
    факт «урок шёл в 214» никуда не девается оттого, что кабинета больше нет.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="rooms",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    name = models.CharField("name", max_length=100)
    is_shared = models.BooleanField(
        "shared",
        default=False,
        help_text=(
            "Несколько занятий разом — норма: спортзал, актовый зал. "
            "О совпадениях в таком кабинете не предупреждаем."
        ),
    )
    is_archived = models.BooleanField(
        "archived",
        default=False,
        help_text="Из выбора убран, в истории остался.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "room"
        verbose_name_plural = "rooms"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "name"), name="unique_room_name_per_school"
            ),
        ]

    def __str__(self):
        return self.name


class BellTime(models.Model):
    """
    Расписание звонков: во сколько начинается и кончается урок с этим номером.

    Справочник **школы**, рядом с предметами и параллелями, и по той же
    причине: звонки одни на всех, ставит их администратор, а читают все.

    **Номер, а не время, остаётся ключом занятия.** Слот по-прежнему знает
    только `lesson_number`, и это не упущение: перенос звонка на десять минут
    не должен переписывать десять тысяч строк расписания. Время живёт здесь и
    подставляется на показ — значит вчерашние занятия сегодня показываются по
    сегодняшним звонкам, и это честно: расписание звонков одно, а не по
    версии на каждый день.

    **Заполнено может быть не всё.** Школа, у которой шесть уроков, заводит
    шесть строк; седьмой номер остаётся без времени, и сетка показывает его
    как раньше — одним номером. Пустой справочник — рабочее состояние, а не
    незаконченная настройка: до звонков жили и так.

    Хранится `TimeField`, а не строка: «8:30» и «08:30» — одно и то же время,
    и решать это сравнением строк пришлось бы в каждом месте показа.
    """

    school = models.ForeignKey(
        "schools.School",
        related_name="bells",
        on_delete=models.CASCADE,
        verbose_name="school",
    )
    number = models.PositiveSmallIntegerField(
        "lesson number",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_LESSON_NUMBER)],
    )
    starts_at = models.TimeField("starts at")
    ends_at = models.TimeField("ends at")

    class Meta:
        verbose_name = "bell time"
        verbose_name_plural = "bell times"
        ordering = ("number",)
        constraints = [
            models.UniqueConstraint(
                fields=("school", "number"), name="one_bell_per_lesson_number"
            ),
            # Урок, кончающийся раньше начала, — не опечатка показа, а
            # сломанная длительность: по ней считают, успевает ли класс
            # перейти, и отрицательная перемена читается как ошибка данных
            # где-то ещё.
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="a_lesson_ends_after_it_starts",
            ),
        ]

    def __str__(self):
        return f"{self.number}: {self.starts_at:%H:%M}–{self.ends_at:%H:%M}"


class CourseAssignment(models.Model):
    """
    Who teaches this course. The one place that answers it.

    Until now the answer only existed inside the school timetable, as the
    `teacher` of a `MasterSlot` — so an administrator could not hand somebody
    a course without also drawing their week, and a teacher with no timetable
    saw an empty list everywhere. Load and timetable are different questions
    and now have different tables.

    **Ведущий учитель у курса один.** Так и в жизни: бывают ассистенты, но
    программу разрабатывает и ведёт один человек. Двое назначенных означали
    бы два расписания под одним курсом — это ещё полбеды — и, пока план был
    личным, две разные программы, о расхождении которых никто бы не узнал.
    Ассистент, если понадобится, будет отдельной ролью: читать и проверять,
    но не править программу.

    У учителя курсов по-прежнему сколько угодно.

    Removing an assignment does **not** touch the lessons or the plan written
    under it — see the delete endpoint. The row is a statement about the
    present, not the owner of the work done in the past.
    """

    course = models.ForeignKey(
        Course,
        related_name="assignments",
        on_delete=models.CASCADE,
        verbose_name="course",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_assignments",
        on_delete=models.CASCADE,
        verbose_name="teacher",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "course assignment"
        verbose_name_plural = "course assignments"
        ordering = ("course__name", "teacher__last_name", "teacher__email")
        constraints = [
            models.UniqueConstraint(fields=("course",), name="one_teacher_per_course"),
        ]

    def __str__(self):
        return f"{self.teacher} — {self.course}"

    def clean(self):
        super().clean()

        if self.course_id and self.teacher_id:
            if self.course.school_id != self.teacher.school_id:
                raise ValidationError(
                    {"teacher": "The teacher belongs to another school."}
                )


class Slot(models.Model):
    """
    Час курса в конкретный день: занятие как событие календаря.

    Именем это стоило двух переименований, и второе объясняется первым.
    `Lesson` он назывался ровно один этап — пока казалось, что записью о
    произошедшем должна быть сама клетка сетки. Оказалось иначе: **урок —
    это строка плана, получившая дату**, а здесь живёт час, в который она
    попала. Слово «слот» и до того стояло во всей документации и в API
    (лента слотов, свободные слоты), так что имя тут догоняет прозу.

    Осей у курса две, и они разные. Календарь — эта модель: когда занятия,
    что сорвалось и чем закрыли; по ней живёт администрация. Программа —
    `plans.PlanNode`: из чего курс состоит; по ней живёт методист. Сливаются
    они в поле `lesson` ниже, и больше нигде.

    Отдельной сущности «расписание» нет: расписание курса на год — это все
    его часы внутри границ года. Вида занятия тоже нет, только два флага:
    обычное — оба False, отменённое — `is_cancelled`, внезапное (замена,
    кружок, перенос) — `is_extra`; комбинация допустима.

    **Час принадлежит курсу, а не учителю.** Личным он был по аналогии с
    тем, что «двое ведут одну параллель, и неделя у каждого своя», — но
    ведущий у курса теперь один, и аналогия отпала вместе с ним. А вот цена
    личного расписания осталась бы: при смене ведущего сентябрь оставался у
    предшественника, январь появлялся у нового, и ни один экран не мог
    сложить их в один год без костыля. Теперь складывать нечего.

    Уникальность `(course, date, lesson_number)` — «курс не может стоять в
    двух местах одновременно». Проверка «учитель не может вести два урока
    разом» идёт через назначение, см. `find_conflict`.
    """

    #: Поля, которые говорят только «когда» и «состоялось ли»: они описывают
    #: клетку сетки, а не то, что в ней произошло.
    #: Кабинет стоит здесь, а не среди записей, и это решение, а не
    #: недосмотр: он говорит, **где** стоит клетка, а не что в ней
    #: произошло. Час, которому проставили кабинет и который так и не
    #: состоялся, — пустая клетка, и массовая чистка вправе её снести.
    GRID_FIELDS = frozenset(
        {"id", "year", "course", "date", "lesson_number", "is_cancelled",
         "is_extra", "room", "created_at"}
    )
    #: Собственные поля, заполненность которых делает занятие историей.
    #: Обратные связи в перечислении не нуждаются, см. `empty_conditions`.
    RECORD_FIELDS = frozenset({"reason", "lesson", "taught_by"})

    year = models.ForeignKey(
        "calendars.SchoolYear",
        related_name="slots",
        on_delete=models.CASCADE,
        verbose_name="school year",
    )
    course = models.ForeignKey(
        Course,
        related_name="slots",
        # PROTECT: an administrator must not wipe somebody's schedule by
        # deleting a course — the answer explains what is in the way
        on_delete=models.PROTECT,
        verbose_name="course",
    )
    date = models.DateField("date")
    lesson_number = models.PositiveSmallIntegerField(
        "lesson number",
        validators=[MinValueValidator(1), MaxValueValidator(MAX_LESSON_NUMBER)],
    )
    is_cancelled = models.BooleanField("cancelled", default=False)
    is_extra = models.BooleanField("extra lesson", default=False)
    reason = models.CharField("reason", max_length=200, blank=True)

    # Урок, который прошёл в этом часе, — точка слияния двух осей.
    #
    # Раскладка отвечает на «что сейчас проходим» и сама, но **позиционно**,
    # и ответ съезжает от любой правки плана. Связь держится за дату.
    #
    # `OneToOne`, потому что одна строка плана — это ровно одно физическое
    # занятие: не успели за урок — в план дописывается строка, успели две
    # темы разом — план правится слиянием. Инвариант держит вся раскладка,
    # и здесь он стоит ограничением базы, а не договорённостью.
    lesson = models.OneToOneField(
        "plans.PlanNode",
        related_name="taught_at",
        null=True,
        blank=True,
        # строку плана могут удалить, а занятие было: связь уходит, час остаётся
        on_delete=models.SET_NULL,
        verbose_name="lesson taught",
        help_text="Строка плана, которую разобрали в этом часе.",
    )
    # кто вёл: обычно ведущий курса, и тогда пусто. Заполняется, когда вёл
    # не он — замена. Это свойство занятия, а не владение расписанием
    taught_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="slots_taught",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="taught by",
        help_text="Заполняется только для замены: обычно урок ведёт ведущий курса.",
    )
    # Где идёт занятие. Необязателен: школа, не ведущая кабинеты, живёт как
    # жила, а пустое поле значит «не указан», а не «неизвестно откуда взять».
    # `PROTECT`: кабинет, в котором уже шли уроки, не исчезает молча — иначе
    # правка справочника переписывала бы историю задним числом
    room = models.ForeignKey(
        Room,
        related_name="slots",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="room",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "slot"
        verbose_name_plural = "slots"
        ordering = ("date", "lesson_number")
        indexes = [
            models.Index(fields=("year", "date"), name="slot_year_date_idx"),
            models.Index(fields=("course", "date"), name="slot_course_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("course", "date", "lesson_number"),
                name="unique_slot_per_course_day",
            ),
            models.CheckConstraint(
                condition=models.Q(lesson_number__gte=1)
                & models.Q(lesson_number__lte=MAX_LESSON_NUMBER),
                name="lesson_number_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.course} {self.date} №{self.lesson_number}"

    @property
    def is_regular(self) -> bool:
        """Обычный урок расписания — только такие копируются и чистятся оптом."""
        return not self.is_extra and not self.is_cancelled

    @classmethod
    def empty_conditions(cls) -> dict:
        """
        Чем занятие доказывает, что на нём **ничего не записано**.

        Возвращается словарь фильтра — «пустая клетка сетки», — и он один на
        всех: по нему работает и `services.sweepable`, и `has_record` ниже.
        Пока условий было два списка, они держались на том, что их правят
        вместе; список — плохое место для инварианта.

        Руками здесь перечислены только **собственные** поля занятия
        (`RECORD_FIELDS`), а любая **обратная** связь считается записью сама
        по себе. Поэтому следующая таблица, повешенная на занятие —
        посещаемость, — защитится от массовой чистки в тот день, когда её
        заведут, а не в тот, когда кто-то вспомнит поправить здешний список.
        А новое собственное поле не даст о себе забыть: `LessonFieldsTests`
        требует, чтобы каждое было названо либо записью, либо временем.
        """
        conditions = {}
        for name in sorted(cls.RECORD_FIELDS):
            field = cls._meta.get_field(name)
            if field.null:
                conditions[f"{name}__isnull"] = True
            else:
                conditions[name] = field.get_default()

        for relation in cls._meta.related_objects:
            conditions[f"{relation.field.related_query_name()}__isnull"] = True

        return conditions

    def has_record(self) -> bool:
        """
        Осталось ли на занятии что-нибудь, кроме времени.

        Пока занятие — пустая клетка сетки, массовая операция вправе его
        снести. Как только на нём появилась запись — отметили, что прошли,
        назвали замену, задали работу, — оно перестаёт быть клеткой и
        становится историей, а историю оптом не чистят.

        Спрашивается это тем же условием, каким чистка отбирает клетки:
        разойтись двум ответам на один вопрос тут негде.
        """
        return not (
            type(self)
            .objects.filter(pk=self.pk, **self.empty_conditions())
            .exists()
        )

    @staticmethod
    def recorded_slots(course):
        """Часы курса с записанной строкой плана, от старых к новым."""
        return Slot.objects.filter(
            course=course, is_cancelled=False, lesson__isnull=False
        ).order_by("date", "lesson_number")

    @staticmethod
    def next_unclosed(course, today):
        """
        Час, который курс закрывает следующим, — или `None`, если нечего.

        Порядок записи строгий и без дырок: прошедший час либо записан («так
        и было»), либо отменён с причиной («не было»). Отменённых здесь нет
        вовсе, и это не упущение: отменённый час закрыт самой отменой.

        Дырка посреди закрытого хвоста — два разных факта в одном виде:
        «провёл, но не отметил» и «не было, а отменить забыл». Пока их не
        различили, неизвестно, сколько курса пройдено, а «пройдено» читает
        методист.

        **Счёт идёт от первой записи.** Учителю, который кнопкой не
        пользуется, каждый прошедший час был бы долгом, и первое же нажатие
        потребовало бы закрыть полгода — то есть не вспомнить, а нажать сто
        раз. До начала учёта работает позиционная догадка, как работала
        всегда; `None` тут значит «закрывать нечего», и первым можно
        записать любой прошедший час.
        """
        past = list(
            Slot.objects.filter(
                course=course, is_cancelled=False, date__lte=today
            ).order_by("date", "lesson_number")
        )

        started = next((i for i, slot in enumerate(past) if slot.lesson_id), None)
        if started is None:
            return None

        return next((slot for slot in past[started:] if slot.lesson_id is None), None)

    @staticmethod
    def broken_record(course, today):
        """
        Час, из-за которого очередь записей курса перестала быть очередью.

        Спрашивают это **после** правки календаря: перенос двигает не строку
        плана, а дату, — и порядок ломается с другого конца. Сломан он двумя
        способами, и оба здесь:

        - **дыра**: незакрытый прошедший час позади последней записи;
        - **обгон**: две записи, у которых даты идут вперёд, а строки плана
          назад. Между ними может не оказаться ни одного живого часа —
          отменённые дыр не образуют, — поэтому одной проверки на дыры мало.

        `None` значит «очередь цела»; курс без записей цел по определению.
        """
        from plans.services import flatten_lessons

        past = list(
            Slot.objects.filter(
                course=course, is_cancelled=False, date__lte=today
            ).order_by("date", "lesson_number")
        )
        recorded = [i for i, slot in enumerate(past) if slot.lesson_id]
        if not recorded:
            return None

        # считаем **от первой записи**, а не от начала года: часы до неё —
        # «до начала учёта», и требовать их закрытия значило бы отменять
        # правило «первая запись ставится на любой прошедший час»
        hole = next(
            (
                slot
                for slot in past[recorded[0] : recorded[-1]]
                if slot.lesson_id is None
            ),
            None,
        )
        if hole is not None:
            return hole

        order = {lesson.node.pk: lesson.number for lesson in flatten_lessons(course.pk)}
        numbered = [(past[i], order.get(past[i].lesson_id, 0)) for i in recorded]
        for (slot, number), (_, before) in zip(numbered[1:], numbered):
            if number <= before:
                return slot

        return None

    @staticmethod
    def last_record(course):
        """Последняя запись курса — единственная, которую можно снять."""
        return Slot.recorded_slots(course).last()

    @classmethod
    def find_conflict(cls, *, teacher_id, year, date, lesson_number, exclude_pk=None):
        """
        Урок того же учителя, уже занявший этот номер в этот день.

        Физически никто не ведёт два урока разом, а уникальность этого не
        ловит: её ключ — курс. Отменённый урок место освобождает: на него
        можно поставить другой курс.

        Учитель ищется через назначение, а не через сам слот: слот теперь
        принадлежит курсу, и «чей это урок» — вопрос к тому, кто курс ведёт.
        """
        if teacher_id is None:
            return None

        queryset = cls.objects.filter(
            course__assignments__teacher_id=teacher_id,
            year=year,
            date=date,
            lesson_number=lesson_number,
            is_cancelled=False,
        ).select_related("course")

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        return queryset.first()

    @classmethod
    def room_clashes(cls, *, school_id, start, end):
        """
        Часы, делящие неделимый кабинет, — одним запросом на весь период.

        **Считается на чтение, а не при записи, и это главное здесь.**
        Занятость кабинета — свойство пары часов, а не одного: конфликт
        возникает не когда вы ставите свой урок, а когда рядом поставят
        чужой. Предупреждение, сказанное один раз в ответе на создание,
        поэтому бесполезно — тот, кто пришёл первым, его никогда не увидит.
        Значит его надо показывать всем и всегда, пока пара стоит рядом.

        Отменённый час кабинет освобождает — тем же правилом, что и номер у
        учителя. Делимый кабинет не считается вовсе: у зала, где два
        занятия разом норма, предупреждение горело бы каждый день и
        приучало бы отмахиваться от всех остальных.

        Возвращает множество id: клетке нужно знать только «я в паре».
        """
        rows = cls.objects.filter(
            course__school_id=school_id,
            date__range=(start, end),
            room__isnull=False,
            room__is_shared=False,
            is_cancelled=False,
        ).values_list("id", "date", "lesson_number", "room_id")

        seats = defaultdict(list)
        for pk, date, number, room_id in rows:
            seats[(date, number, room_id)].append(pk)

        return {pk for shared in seats.values() if len(shared) > 1 for pk in shared}

    @staticmethod
    def homegroups_by_course(school_id):
        """
        Классы каждого курса — выведенные из его учеников, одним запросом.

        Записанной связи «курс — класс» не существует, и это решение, а не
        пробел: она была бы вторым ответом на вопрос, на который уже
        отвечают зачисления, и разошлась бы с ними молча. «Курс 6А», в
        котором семеро из 6А и трое из 6Б, — обычное дело, а в поле стояло
        бы «6А».

        Цена названа прямо: курс, в который никого не зачислили, классов не
        имеет вовсе — и в дневном виде «по классам» уходит в крайний столбец
        «не указан». Расписание рисуют в августе, а зачисляют в сентябре, и
        всё это время так и будет.
        """
        from collections import defaultdict

        rows = (
            CourseStudent.objects.filter(
                removed_at__isnull=True,
                course__school_id=school_id,
                student__homegroups__removed_at__isnull=True,
            )
            .values_list("course_id", "student__homegroups__homegroup_id")
            .distinct()
        )

        found = defaultdict(set)
        for course_id, group_id in rows:
            if group_id is not None:
                found[course_id].add(group_id)

        return {course_id: sorted(groups) for course_id, groups in found.items()}

    @classmethod
    def student_clashes(cls, *, school_id, start, end):
        """
        Часы, у которых в один номер попал один и тот же ученик.

        Это то, ради чего классы вообще заведены, и это **не** «класс занят»:
        две подгруппы 6А в третьем часу — норма, ровно для того их и делят.
        Ошибка — когда в обеих оказался Иванов, а физически он один.

        Считается по самим ученикам, а не по классам, и потому работает и
        там, где классов как таковых нет: в школе с выбором предметов каждый
        курс собран из кусков разных классов, а вопрос «где сейчас этот
        человек» остаётся тем же самым.

        Предупреждение, а не запрет — как и с кабинетом: сдвоенные занятия,
        консультации и отработки бывают, и отказ заставил бы расписание
        врать. Возвращается `{id часа: [имена учеников]}`: клетке нужно и
        «я в паре», и кого назвать в подсказке.

        Отменённый час не считается: ученика на нём нет.
        """
        from collections import defaultdict

        rows = (
            CourseStudent.objects.filter(
                removed_at__isnull=True,
                course__school_id=school_id,
                course__slots__date__range=(start, end),
                course__slots__is_cancelled=False,
            )
            .values_list(
                "course__slots__id",
                "course__slots__date",
                "course__slots__lesson_number",
                "student_id",
                "student__first_name",
                "student__last_name",
                "student__email",
            )
        )

        # «кто где стоит» — по окну (дата и номер), а внутри по ученику:
        # один ученик в двух курсах одного окна и есть весь конфликт
        windows = defaultdict(lambda: defaultdict(set))
        names = {}
        for slot_id, date, number, student_id, first, last, email in rows:
            windows[(date, number)][student_id].add(slot_id)
            names[student_id] = " ".join(filter(None, (first, last))) or email

        found = defaultdict(set)
        for seats in windows.values():
            for student_id, slot_ids in seats.items():
                if len(slot_ids) < 2:
                    continue
                for slot_id in slot_ids:
                    found[slot_id].add(names[student_id])

        return {slot_id: sorted(who) for slot_id, who in found.items()}

    def student_clash(self):
        """
        Те же пересечения, но про один час: у одиночного ответа периода нет.

        Тот же приём, что у кабинета рядом, и по той же причине: один запрос
        про один час дешевле, чем обход недели на каждый PATCH.
        """
        if self.is_cancelled or not self.course_id:
            return []
        if self.date is None or self.lesson_number is None:
            return []

        mine = set(
            CourseStudent.objects.filter(
                course_id=self.course_id, removed_at__isnull=True
            ).values_list("student_id", flat=True)
        )
        if not mine:
            return []

        rows = (
            CourseStudent.objects.filter(
                removed_at__isnull=True,
                student_id__in=mine,
                course__slots__date=self.date,
                course__slots__lesson_number=self.lesson_number,
                course__slots__is_cancelled=False,
            )
            .exclude(course__slots__id=self.pk)
            .values_list("student__first_name", "student__last_name", "student__email")
        )

        return sorted(
            {" ".join(filter(None, (first, last))) or email for first, last, email in rows}
        )

    def shares_room(self) -> bool:
        """
        Делит ли **этот** час неделимый кабинет с другим.

        Один запрос про один час — для ответа, в котором слот приехал сам по
        себе (создание, правка). Списку это не годится: там за тем же
        ответом ходит `room_clashes`, один раз на весь период.
        """
        if self.room_id is None or self.is_cancelled:
            return False
        if self.date is None or self.lesson_number is None:
            return False
        if self.room.is_shared:
            return False

        return (
            Slot.objects.filter(
                room_id=self.room_id,
                date=self.date,
                lesson_number=self.lesson_number,
                is_cancelled=False,
            )
            .exclude(pk=self.pk)
            .exists()
        )

    def lead_teacher_id(self):
        """Кто ведёт курс этого слота; None — нагрузку ещё не раздали."""
        if not self.course_id:
            return None

        return (
            CourseAssignment.objects.filter(course_id=self.course_id)
            .values_list("teacher_id", flat=True)
            .first()
        )

    def conflict(self):
        if self.is_cancelled or not (self.year_id and self.course_id):
            return None
        if self.date is None or self.lesson_number is None:
            return None

        return self.find_conflict(
            teacher_id=self.lead_teacher_id(),
            year=self.year,
            date=self.date,
            lesson_number=self.lesson_number,
            exclude_pk=self.pk,
        )

    def clean(self):
        super().clean()

        busy = self.conflict()
        if busy is not None:
            raise ValidationError(
                {
                    "lesson_number": services.occupied_message(
                        self.date, self.lesson_number, busy.course.name
                    )
                }
            )


class Attendance(models.Model):
    """
    Кто был на занятии. Строка на человека, и только у отмеченных.

    Первая таблица, которая висит на занятии по-настоящему: у остальных на
    нём одно поле. Форма та же, что у оценок и отправок, — **строка заводится
    по требованию**. Пока никого не отметили, строк нет, и «не отмечено»
    отличается от «отсутствовал» тем, что первого просто нет в базе.
    Различать их обязательно: пустой журнал и журнал, где весь класс
    отсутствовал, — разные вещи, а хранить «не отмечено» значением значило бы
    заводить строку на каждого ученика каждого занятия года.

    Состояний три, и больше не нужно. «Опоздал» отдельно от «был», потому
    что это единственная пометка, которую учитель ставит на ходу и которая
    потом что-то значит; «болел», «по заявлению» и прочие причины — это
    `note`, а не новый вид: список причин у каждой школы свой, и угадывать
    его нельзя.

    **Состав курса на дату восстанавливается приблизительно**, и это
    известный предел. Строка зачисления одна навсегда, `removed_at`
    переключается, поэтому «сняли в октябре, вернули в феврале» делает
    октябрь неотличимым от обычного. Журнал от этого не страдает — он про
    тех, кого отметили, — а вот «сколько человек было в списке 12 октября»
    ответить нечем. Первым это спросит отчёт по пропускам.

    Занятие уносит свои строки каскадом: журнал существует ради занятия, и
    без него не значит ничего. А `Slot.empty_conditions` защищает занятие с
    журналом от массовой чистки — само, потому что считает записью любую
    обратную связь.
    """

    class Status(models.TextChoices):
        PRESENT = "present", "was there"
        ABSENT = "absent", "was not"
        LATE = "late", "came late"

    slot = models.ForeignKey(
        "schedule.Slot",
        related_name="attendance",
        on_delete=models.CASCADE,
        verbose_name="lesson",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="attendance",
        on_delete=models.CASCADE,
        verbose_name="student",
    )
    status = models.CharField("status", max_length=8, choices=Status)
    note = models.CharField(
        "note",
        max_length=200,
        blank=True,
        help_text="Причина словами: список причин у каждой школы свой.",
    )
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="attendance_marked",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="marked by",
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "attendance mark"
        verbose_name_plural = "attendance"
        ordering = ("student__last_name", "student__email")
        constraints = [
            models.UniqueConstraint(
                fields=("slot", "student"), name="one_attendance_row_per_lesson"
            ),
        ]

    def __str__(self):
        return f"{self.student} — {self.get_status_display()}"
