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

    def for_student(self, user, *, active_only=True):
        """
        Курсы ученика. Два вопроса одной функцией — и это не удобство.

        «Можно работать» и «можно видеть своё» — разные права: снятый с
        курса продолжает читать сделанное, но ничего в нём не делает. Пока
        оба ответа даёт одно место, разойтись им негде; разложенные по
        queryset'ам, они разойдутся в первом же забытом фильтре — с
        учительскими выборками это уже происходило.
        """
        if user is None or not user.is_authenticated or user.school_id is None:
            return self.none()

        enrolled = self.filter(students__student=user, school_id=user.school_id)
        if active_only:
            enrolled = enrolled.filter(students__removed_at__isnull=True)

        return enrolled.distinct()


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
    GRID_FIELDS = frozenset(
        {"id", "year", "course", "date", "lesson_number", "is_cancelled",
         "is_extra", "created_at"}
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
