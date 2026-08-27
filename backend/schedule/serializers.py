from calendars import services as calendar_services
from calendars.serializers import CurrentSchoolDefault, school_years
from config.errors import Codes, api_error, error_payload
from calendars.models import SchoolYear
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import services
from .models import (
    MAX_LESSON_NUMBER,
    Attendance,
    Course,
    CourseAssignment,
    CourseMethodist,
    CourseStudent,
    GradeLevel,
    Homegroup,
    HomegroupStudent,
    Room,
    Slot,
    Subject,
)

User = get_user_model()


def full_name(person) -> str:
    """A person as a list shows them: their name, or the address they signed in with."""
    return f"{person.first_name} {person.last_name}".strip() or person.email


def school_teachers(serializer):
    """
    Учителя школы — единственные, кого можно назвать в уроке.

    Именно учителя, а не «люди школы»: с появлением учеников это перестало
    быть одним и тем же, и без сужения администратор поставил бы ученика
    вести урок.
    """
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return User.objects.none()
    return User.objects.filter(school_id=user.school_id, kind=User.Kind.TEACHER)


def school_rooms(serializer):
    """
    Кабинеты своей школы — единственные, которые можно назвать в занятии.

    Сужение здесь по тому же доводу, что у курса и учителя рядом: ключ в
    теле запроса проходит мимо фильтра вьюхи, и без выборки занятие можно
    было бы поставить в кабинет чужой школы. Стоило бы это не только
    неверной записи: имя кабинета едет обратно в `room_name`, то есть
    ответ рассказывал бы, как называются кабинеты у соседей.

    Архивные остаются: из **выбора** они убраны на экране, а запрос может
    прийти и про давнее занятие, которое в этом кабинете как раз и шло.
    """
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return Room.objects.none()
    return Room.objects.filter(school_id=user.school_id)


def school_courses(serializer):
    """
    Courses of the requester's school — another school's cannot be referenced.

    A foreign key in the body bypasses the viewset's filter, so the choices
    are narrowed here as well.
    """
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return Course.objects.none()
    return Course.objects.filter(school_id=user.school_id)


def teacher_courses(serializer):
    """
    Курсы, в которых спрашивающий вправе что-то заводить.

    Урок, строка плана и шаблон, взятый в курс, принадлежат курсу, и
    заводить их может тот, кто вправе его править: назначенный ведущий —
    свои, администратор школы — любые её (`writable_by`). Членства в школе
    при этом мало: у рядового учителя чужой курс закрыт по-прежнему.

    Имя осталось прежним, а вот вопрос это **про право**, не про «мои
    курсы»: второе отвечает `for_teacher`, и путать их нельзя — у завуча
    это разные списки.
    """
    user = getattr(serializer.context.get("request"), "user", None)
    return Course.objects.writable_by(user)


class SubjectSerializer(serializers.ModelSerializer):
    """A subject of the school. Administrators keep the list."""

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    # аннотация из вьюсета, а не `source="courses.count"`: второе — запрос
    # на строку, и на одиннадцати параллелях это одиннадцать лишних
    courses = serializers.SerializerMethodField()

    def get_courses(self, subject) -> int:
        return getattr(subject, "course_count", 0)

    class Meta:
        model = Subject
        fields = ("id", "school", "name", "courses")
        validators = [
            UniqueTogetherValidator(
                queryset=Subject.objects.all(),
                fields=("school", "name"),
                message="This school already has a subject with that name.",
            ),
        ]


class HomegroupSerializer(serializers.ModelSerializer):
    """
    Класс: имя, параллель, классный руководитель и сколько в нём человек.

    Связи с курсами тут нет и не будет: класс курса выводится из его
    учеников (см. `Homegroup` в моделях). Наружу отдаётся только состав —
    числом, потому что списком его смотрят на своём экране.
    """

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    tutor_name = serializers.SerializerMethodField()
    grade_name = serializers.CharField(source="grade.name", read_only=True)
    students = serializers.SerializerMethodField()

    def get_tutor_name(self, group) -> str:
        return full_name(group.tutor) if group.tutor_id else ""

    def get_students(self, group) -> int:
        return getattr(group, "student_count", 0)

    class Meta:
        model = Homegroup
        fields = (
            "id",
            "school",
            "year",
            "grade",
            "grade_name",
            "name",
            "tutor",
            "tutor_name",
            "students",
        )
        validators = [
            UniqueTogetherValidator(
                queryset=Homegroup.objects.all(),
                fields=("school", "year", "name"),
                message="This school already has a homegroup with that name this year.",
            ),
        ]


class HomegroupStudentSerializer(serializers.ModelSerializer):
    """
    Кто в классе. Та же форма, что у зачисления на курс, и та же причина.

    Строка не удаляется: перевод из 6А в 6Б посреди года не должен стирать,
    что человек был в 6А, — расписание сентября собиралось по тому составу.
    Снятие ставит `removed_at`, возврат его снимает.
    """

    student_name = serializers.SerializerMethodField()

    def get_student_name(self, row) -> str:
        return full_name(row.student)

    class Meta:
        model = HomegroupStudent
        fields = ("id", "homegroup", "student", "student_name", "removed_at")
        read_only_fields = ("removed_at",)

    def validate(self, attrs):
        """
        Класс на год у ученика один — и отказ должен называть, какой именно.

        Ограничение стоит в базе, но её сообщение человеку ничего не
        говорит: ловим раньше и называем класс, в котором он уже числится.
        """
        student = attrs.get("student")
        group = attrs.get("homegroup")
        if not student or not group:
            return attrs

        busy = (
            HomegroupStudent.objects.filter(
                student=student, year=group.year, removed_at__isnull=True
            )
            .exclude(homegroup=group)
            .select_related("homegroup")
            .first()
        )
        if busy:
            api_error(
                Codes.HOMEGROUP_TAKEN,
                f"{full_name(student)} already belongs to «{busy.homegroup.name}» "
                "this year.",
                field="student",
                name=full_name(student),
                homegroup=busy.homegroup.name,
            )

        return attrs


class RoomSerializer(serializers.ModelSerializer):
    """
    Кабинет школы. Список ведёт администратор, выбирают из него все.

    `slots` — сколько часов на него уже ссылается: то же число, что у
    предмета рядом, и нужно оно там же, где у предмета, — в отказе на
    удаление. Аннотацией из вьюсета, а не `source`, по той же причине: на
    сорока кабинетах это сорок лишних запросов.
    """

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    slots = serializers.SerializerMethodField()

    def get_slots(self, room) -> int:
        return getattr(room, "slot_count", 0)

    class Meta:
        model = Room
        fields = ("id", "school", "name", "is_shared", "is_archived", "slots")
        validators = [
            UniqueTogetherValidator(
                queryset=Room.objects.all(),
                fields=("school", "name"),
                message="This school already has a room with that name.",
            ),
        ]


class GradeLevelSerializer(serializers.ModelSerializer):
    """A year group of the school. Administrators keep the list."""

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    # аннотация из вьюсета, а не `source="courses.count"`: второе — запрос
    # на строку, и на одиннадцати параллелях это одиннадцать лишних
    courses = serializers.SerializerMethodField()

    def get_courses(self, grade) -> int:
        return getattr(grade, "course_count", 0)

    class Meta:
        model = GradeLevel
        fields = ("id", "school", "level", "name", "courses")
        validators = [
            UniqueTogetherValidator(
                queryset=GradeLevel.objects.all(),
                fields=("school", "level"),
                message="This school already has a year group at that level.",
            ),
        ]

    def validate_level(self, value):
        """
        The year of study is fixed once courses point at it.

        Renaming is free — the name is a label. Moving the level is not: the
        courses sitting on it would silently change places in every sorted
        list, and nothing on screen would say why. An empty year group can
        still be moved, which covers the usual case of a typo.
        """
        if self.instance and value != self.instance.level:
            used = self.instance.courses.count()
            if used:
                api_error(
                    Codes.GRADE_LEVEL_LOCKED,
                    f"«{self.instance.name}» is used by {used} courses, so its "
                    "year of study cannot be moved — the sorting of every list "
                    "depends on it. Rename it instead.",
                    field="level",
                    name=self.instance.name,
                    courses=used,
                )

        return value


class TeacherBriefSerializer(serializers.ModelSerializer):
    """Just enough of a person to show them in a list."""

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "is_school_admin")


def refuse_if_hours_collide(course, teacher) -> None:
    """
    Ведущего не ставят на курс, если этот час у него уже занят.

    Физически человек не ведёт два урока разом, и приложение это правило
    держит везде: `Slot.find_conflict` не даёт завести такой урок, а
    `rich_demo.check_conflicts` считает такое состояние невозможным. Одна
    дверь стояла открытой — **назначение**: курс, оставшийся без ведущего,
    сохраняет своё расписание, и новый человек мог получить его поверх
    собственных часов. Проходило это молча, а разбираться пришлось бы уже
    по экранам, где один учитель стоит в двух местах.

    Отказ жёсткий, без `?force=`: это не «дорого, но бывает», а состояние,
    которого не бывает. Расписание правят и назначают снова — тем же
    порядком, каким чинят любое столкновение часов.
    """
    if teacher is None:
        return

    hours = set(
        Slot.objects.filter(course=course, is_cancelled=False).values_list(
            "date", "lesson_number"
        )
    )
    if not hours:
        return

    busy = (
        Slot.objects.filter(
            course__assignments__teacher=teacher,
            is_cancelled=False,
            date__in={day for day, _ in hours},
        )
        .exclude(course=course)
        .select_related("course")
        .order_by("date", "lesson_number")
    )

    clashes = [slot for slot in busy if (slot.date, slot.lesson_number) in hours]
    if not clashes:
        return

    first = clashes[0]
    api_error(
        Codes.COURSE_TEACHER_BUSY,
        f"{full_name(teacher)} already teaches «{first.course.name}» on "
        f"{first.date}, lesson {first.lesson_number}: {len(clashes)} hours of "
        "this course collide with their timetable.",
        field="teacher",
        teacher=full_name(teacher),
        course=first.course.name,
        date=str(first.date),
        number=first.lesson_number,
        count=len(clashes),
    )


class CourseAssignmentSerializer(serializers.ModelSerializer):
    """
    Кто ведёт курс. Пишется с обеих сторон, хранится в одном месте.

    Ведущий у курса **один**: так и бывает в школе — ассистенты бывают, а
    разработчик программы один, и план у курса тоже один. Второй человек на
    том же курсе отклоняется кодом `course_teacher_taken`, называя того, кто
    там уже стоит: «занято» без имени отправляет искать его руками.
    """

    teacher_name = serializers.SerializerMethodField()
    course_name = serializers.CharField(source="course.name", read_only=True)

    class Meta:
        model = CourseAssignment
        fields = ("id", "course", "course_name", "teacher", "teacher_name", "created_at")
        read_only_fields = ("created_at",)
        validators = [
            UniqueTogetherValidator(
                queryset=CourseAssignment.objects.all(),
                fields=("course", "teacher"),
                message="This teacher is already assigned to this course.",
            ),
        ]

    def get_teacher_name(self, assignment) -> str:
        return full_name(assignment.teacher)

    def get_fields(self):
        fields = super().get_fields()
        # both ends stay inside the requester's school
        fields["course"].queryset = school_courses(self)
        fields["teacher"].queryset = school_teachers(self)
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        course = attrs.get("course")
        if course is None:
            return attrs

        taken = (
            CourseAssignment.objects.filter(course=course)
            .exclude(pk=self.instance.pk if self.instance else None)
            .select_related("teacher")
            .first()
        )
        if taken is not None:
            api_error(
                Codes.COURSE_TEACHER_TAKEN,
                f"«{course.name}» is already taught by "
                f"{full_name(taken.teacher)}. Remove that assignment first.",
                field="teacher",
                course=course.name,
                teacher=full_name(taken.teacher),
            )

        refuse_if_hours_collide(course, attrs.get("teacher"))
        return attrs


class CourseSerializer(serializers.ModelSerializer):
    # the school comes from the requester, never from the body
    school = serializers.HiddenField(default=CurrentSchoolDefault())
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    grade_name = serializers.CharField(source="grade.name", read_only=True)
    grade_level = serializers.IntegerField(source="grade.level", read_only=True)
    teachers = serializers.SerializerMethodField()
    methodists = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    # классы курса — выведенные из его учеников, а не записанные полем.
    # Тем же расчётом, что у часа: два ответа на один вопрос разъехались бы
    homegroups = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = (
            "id",
            "school",
            "year",
            "subject",
            "subject_name",
            "grade",
            "grade_name",
            "grade_level",
            "teachers",
            "methodists",
            "students",
            "homegroups",
            "name",
            "created_at",
        )
        read_only_fields = ("created_at",)
        validators = [
            # school is not in the request body, so DRF cannot check
            # unique_together on its own — a duplicate would give a 500
            UniqueTogetherValidator(
                queryset=Course.objects.all(),
                fields=("school", "year", "name"),
                message="A course with this name already exists in this year.",
            ),
        ]

    def get_homegroups(self, course):
        known = self.context.get("course_homegroups")
        if known is not None:
            return known().get(course.id, [])

        return Slot.homegroups_by_course(course.school_id).get(course.id, [])

    def get_students(self, course) -> int:
        """
        Сколько человек учится — число, а не список.

        Список класса это тридцать строк, и в свёрнутой карточке курса им
        делать нечего; открывают его отдельным окном, где он и нужен.
        Аннотацию ставит вьюсет: без неё у только что созданного курса
        учеников ноль, и это правда.
        """
        return getattr(course, "active_students", 0)

    def get_methodists(self, course) -> list:
        """
        Кто утверждает план этого курса — вторая строка карточки курса.

        Приходит вместе с курсом по той же причине, что и учителя: экран
        показывает обе роли рядом, и спрашивать их по строке значило бы
        рисовать карточку в два приёма.
        """
        return [
            {"id": item.user_id, "name": full_name(item.user), "row": item.pk}
            for item in course.methodists.all()
        ]

    def get_teachers(self, course) -> list:
        """
        Who teaches it — the same answer the teacher's own card gives.

        Sent with the course because both screens need it and neither should
        have to ask again per row.
        """
        return [
            {
                "id": item.teacher_id,
                "name": full_name(item.teacher),
                # приглашение заводит учётку сразу, поэтому ведущий у курса
                # бывает и такой, который ещё ни разу не входил
                "arrived": item.teacher.last_login is not None,
            }
            for item in course.assignments.all()
        ]

    def get_fields(self):
        fields = super().get_fields()
        school_id = getattr(self.context.get("request").user, "school_id", None)
        # a course can only live in a year of its own school
        fields["year"].queryset = school_years(self)
        fields["subject"].queryset = Subject.objects.filter(school_id=school_id)
        fields["grade"].queryset = GradeLevel.objects.filter(school_id=school_id)
        return fields


class SlotSerializer(serializers.ModelSerializer):
    # the year follows from the course and need not be sent
    year = serializers.PrimaryKeyRelatedField(
        queryset=SchoolYear.objects.none(), required=False
    )
    course_name = serializers.CharField(source="course.name", read_only=True)
    # ведущий курса: не поле урока, а вывод из назначения. Наружу только на
    # чтение — расписание школы показывает, кто ведёт, и брать это из
    # второго места было бы вторым ответом на один вопрос
    teacher = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True)
    # классы курса — выведенные из его учеников, а не записанные полем:
    # см. `Slot.homegroups_by_course`. Нужны дневному виду «по классам»
    homegroups = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()
    # долг — прошедший час без записи в курсе, где запись уже начали. То же
    # правило, что в сводном расписании; там оно считается своим кодом,
    # потому что тот ответ строится не сериализатором
    debt = serializers.SerializerMethodField()

    class Meta:
        model = Slot
        fields = (
            "id",
            "year",
            "course",
            "course_name",
            "teacher",
            "teacher_name",
            "lesson",
            "lesson_title",
            "taught_by",
            "date",
            "lesson_number",
            "is_cancelled",
            "is_extra",
            "reason",
            "room",
            "room_name",
            "homegroups",
            "created_at",
            "warnings",
            "debt",
        )
        read_only_fields = ("created_at",)
        validators = [
            # та же уникальность, что у школьного расписания: курс не может
            # стоять в двух местах одновременно
            UniqueTogetherValidator(
                queryset=Slot.objects.all(),
                fields=("course", "date", "lesson_number"),
                message="This course already has a lesson with that number that day.",
            ),
        ]

    def get_debt(self, obj):
        """
        Прошедший час без записи — и только там, где запись уже начали.

        Список «начавших» приходит из контекста **функцией**: она нужна
        только на чтение списка, а контекст строится и на запись тоже, и
        лишний запрос на каждый PATCH ни к чему.
        """
        started = self.context.get("recorded_courses")
        if started is None or obj.is_cancelled or obj.lesson_id is not None:
            return False

        return obj.date <= timezone.localdate() and obj.course_id in started()

    def get_fields(self):
        fields = super().get_fields()
        # курсы всей школы: расписание правит и ведущий, и администратор, а
        # кому какой курс дозволен, спрашивает вьюха (`require_write`).
        # Сузить поле до своих значило бы отвечать администратору «нет
        # такого курса» вместо «это не ваш курс»
        courses = school_courses(self)
        fields["course"].queryset = courses
        fields["year"].queryset = SchoolYear.objects.filter(
            pk__in=courses.values("year_id")
        )
        # что прошли — строка плана этих же курсов, и только урок: тему не
        # проходят, её проходят по частям
        from plans.models import PlanNode

        fields["lesson"].queryset = PlanNode.objects.filter(
            course__in=courses, is_section=False
        )
        # уникальность связи проверяем сами, см. `validate` ниже: DRF вешает
        # на `OneToOne` свой валидатор, а тот отказывает английской строкой
        # без кода и, главное, без даты, за которой урок уже записан
        fields["lesson"].validators = []
        # кто вёл — сотрудник школы: замену ведёт учитель, а не ученик
        fields["taught_by"].queryset = school_teachers(self)
        # где идёт — кабинет своей школы. Сужается наравне с остальными
        # ключами: без этого чужой кабинет проставился бы молча, а его имя
        # уехало бы обратно в `room_name`
        fields["room"].queryset = school_rooms(self)
        return fields

    def lead(self, obj):
        """Назначение курса; выборка предвыбрана вьюхой, запросов нет."""
        rows = list(obj.course.assignments.all())
        return rows[0].teacher if rows else None

    def get_teacher(self, obj):
        lead = self.lead(obj)
        return lead.pk if lead else None

    def get_teacher_name(self, obj):
        lead = self.lead(obj)
        return full_name(lead) if lead else None

    def get_warnings(self, obj):
        """
        Что с этим часом не так — списком, а не одним полем.

        Полем это было, пока предупреждение было одно: урок в неучебный
        день. Их стало больше — занятый кабинет, а дальше ученик, стоящий в
        двух местах, — и складываются они свободно: урок в субботу вполне
        может ещё и делить кабинет. Одно поле заставило бы выбирать, о чём
        промолчать, а промолчать нельзя ни о чём: запрета тут нет ни у
        одного из них, и предупреждение — единственное, что вообще
        сказано.

        Порядок — от общего к частному: сперва про день целиком, потом про
        этот час.
        """
        found = []

        day = calendar_services.resolve_day(
            obj.date, obj.year.weekend_days, obj.year.periods()
        )
        if not day.is_study:
            label = calendar_services.STATUS_LABELS[day.status]
            note = f" «{day.title}»" if day.title else ""
            found.append(
                error_payload(
                    Codes.SLOT_NOT_STUDY_DAY,
                    f"{obj.date.isoformat()} is a {label}{note}: "
                    "the lesson falls outside study days.",
                    date=obj.date.isoformat(),
                    status=day.status,
                    title=day.title,
                )
            )

        clash = self.student_clash(obj)
        if clash:
            more = len(clash) - 3
            listed = ", ".join(clash[:3]) + (f" (+{more})" if more > 0 else "")
            found.append(
                error_payload(
                    Codes.SLOT_STUDENT_BUSY,
                    f"{listed} also have another lesson at number "
                    f"{obj.lesson_number} on {obj.date.isoformat()}.",
                    students=clash,
                    names=listed,
                    count=len(clash),
                    lesson_number=obj.lesson_number,
                )
            )

        if self.room_taken(obj):
            found.append(
                error_payload(
                    Codes.SLOT_ROOM_BUSY,
                    f"Room «{obj.room.name}» holds another lesson "
                    f"at number {obj.lesson_number} on {obj.date.isoformat()}.",
                    room=obj.room.name,
                    date=obj.date.isoformat(),
                    lesson_number=obj.lesson_number,
                )
            )

        return found

    def get_homegroups(self, obj):
        """
        Классы этого часа: классы учеников его курса.

        Списку набор курсов известен заранее, и вывод считается **одним**
        запросом на ответ (`course_homegroups` в контексте вьюсета) — тем же
        приёмом, что занятость кабинета и пересечения по ученикам рядом.
        Одиночному ответу считать нечего сообща, и он спрашивает про свой
        курс сам.
        """
        known = self.context.get("course_homegroups")
        if known is not None:
            return known().get(obj.course_id, [])

        return Slot.homegroups_by_course(obj.course.school_id).get(obj.course_id, [])

    def student_clash(self, obj):
        """
        Кто из учеников этого часа стоит в это же время ещё где-то.

        Тем же приёмом, что и занятость кабинета: списку набор клеток
        известен заранее, и пересечения считаются **одним** запросом на весь
        период; одиночный ответ спрашивает про себя сам.
        """
        clashes = self.context.get("student_clashes")
        if clashes is not None:
            return clashes().get(obj.id, [])

        return obj.student_clash()

    def room_taken(self, obj) -> bool:
        """
        Делит ли час неделимый кабинет с соседним.

        Ответу-списку набор клеток известен заранее, и он считается **одним**
        запросом на весь период (`room_clashes` в контексте вьюсета) — как
        список «начавших запись» для долгов рядом. Одиночному ответу считать
        нечего сообща, и он спрашивает про себя сам: один запрос про один
        час дешевле, чем лишний обход всей недели на каждый PATCH.
        """
        if obj.room_id is None:
            return False

        clashes = self.context.get("room_clashes")
        if clashes is not None:
            return obj.id in clashes()

        return obj.shares_room()

    def check_record_order(self, course, lesson):
        """
        Записи идут подряд, и снять можно только последнюю.

        Дырка посреди закрытого хвоста — два разных факта в одном виде:
        «провёл, но не отметил» и «не было, а отменить забыл»; пока их не
        различили, «сколько курса пройдено» неизвестно.

        Снятие ограничено последней записью потому, что следа у него нет: у
        оценки исправление — событие (`MarkChange`), а тут поле молча
        возвращается в пустоту. Отмена последнего действия — это ещё не
        переписывание прошлого; всё, что глубже, им уже было бы.
        """
        today = timezone.localdate()
        slot = self.instance
        was = slot.lesson_id

        if lesson is None:
            if was is None:
                return None
            last = Slot.last_record(course)
            if last is None or last.pk != slot.pk:
                api_error(
                    Codes.SLOT_RECORD_NOT_LAST,
                    "Only the last record of a course can be withdrawn.",
                    field="lesson",
                    date=str(last.date) if last else "",
                    number=last.lesson_number if last else 0,
                )
            return None

        if slot.date > today:
            api_error(
                Codes.SLOT_RECORD_FUTURE,
                "A lesson can only be recorded once it has happened.",
                field="lesson",
            )

        # правка уже записанного — то же переписывание прошлого, что и снятие
        if was is not None:
            last = Slot.last_record(course)
            if last is None or last.pk != slot.pk:
                api_error(
                    Codes.SLOT_RECORD_NOT_LAST,
                    "Only the last record of a course can be changed.",
                    field="lesson",
                    date=str(last.date) if last else "",
                    number=last.lesson_number if last else 0,
                )
            return None

        nxt = Slot.next_unclosed(course, today)
        if nxt is not None and nxt.pk != slot.pk:
            api_error(
                Codes.SLOT_RECORD_OUT_OF_ORDER,
                f"Close {nxt.date} first: records go in order, without gaps.",
                field="lesson",
                date=str(nxt.date),
                number=nxt.lesson_number,
            )

        suggested = services.suggested_topics(course).get(slot.pk)
        if suggested is None:
            api_error(
                Codes.SLOT_RECORD_NO_ROW,
                "The plan has no row left for this hour — add one first.",
                field="lesson",
            )
        return suggested

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        course = value("course")
        year = attrs.get("year") or course.year
        slot_date = value("date")

        lesson = value("lesson")

        # Порядок проверок — от частного к общему, и он не случаен: человек
        # должен получить самое узкое объяснение из верных.
        #
        #   1. строка чужого курса — про саму строку;
        #   2. очередь: будущее, не последняя, не по порядку — про час;
        #   3. «в плане не осталось строки» — тоже про час, и раньше «занято»:
        #      когда план исчерпан, **любая** названная строка окажется
        #      записанной, и человек пойдёт разбираться не туда;
        #   4. строка занята другим днём — про строку;
        #   5. и только потом «раскладка предлагает другую».
        if lesson is not None and lesson.course_id != course.pk:
            api_error(
                Codes.PARENT_OTHER_CLASS,
                "That plan lesson belongs to another course.",
                field="lesson",
            )

        suggested = None
        if self.instance is not None and "lesson" in attrs:
            suggested = self.check_record_order(course, lesson)

        if lesson is not None:
            # одна строка плана — ровно одно занятие. Сказать надо не
            # «занято», а **где** занято: иначе это искать руками
            taken = (
                Slot.objects.filter(lesson=lesson)
                .exclude(pk=self.instance.pk if self.instance else None)
                .first()
            )
            if taken is not None:
                api_error(
                    Codes.SLOT_LESSON_TAKEN,
                    f"«{lesson.title}» is already recorded on {taken.date}.",
                    field="lesson",
                    title=lesson.title,
                    date=str(taken.date),
                )

        # строка тоже не выбирается: записывается та, которую предлагает
        # раскладка. Правило было и раньше, но держалось тем, что в
        # интерфейсе выбора негде взять; по API можно было записать любую,
        # оставив предыдущие строки неиспользованными — и они молча уезжали
        # на более поздние дни. Пропуск темы выражается теперь перестановкой
        # строки в плане, то есть видимой правкой программы
        if suggested is not None and lesson is not None and suggested.pk != lesson.pk:
            api_error(
                Codes.SLOT_RECORD_NOT_SUGGESTED,
                f"The layout puts «{suggested.title}» in this hour.",
                field="lesson",
                title=suggested.title,
            )

        # Отмена записанного часа — то же стирание записи, что и удаление,
        # только исподтишка: `Slot.lesson` остаётся, а очередь и раскладка
        # отменённых не видят. Строка плана после такого заперта навсегда —
        # снять запись нельзя, она уже не последняя.
        if value("is_cancelled") and value("lesson") is not None:
            api_error(
                Codes.SLOT_CANCEL_RECORDED,
                f"«{value('lesson').title}» is recorded here: withdraw the "
                "record before cancelling the lesson.",
                field="is_cancelled",
                title=value("lesson").title,
            )

        if year != course.year:
            api_error(
                Codes.SLOT_YEAR_MISMATCH,
                "The lesson year must match the year of its course.",
                field="year",
            )

        if not year.start_date <= slot_date <= year.end_date:
            api_error(
                Codes.SLOT_OUTSIDE_YEAR,
                "The date is outside the school year "
                f"({year.start_date} — {year.end_date}).",
                field="date",
                start=str(year.start_date),
                end=str(year.end_date),
            )

        if not value("is_cancelled"):
            # двух уроков разом не бывает — но у **ведущего курса**, а не у
            # того, кто нажал: администратор рисует чужую сетку, и мешать ей
            # может только чужое же расписание. Курс без ведущего не мешает
            # никому: некому
            lead = CourseAssignment.objects.filter(course=course).values_list(
                "teacher_id", flat=True
            ).first()
            busy = Slot.find_conflict(
                teacher_id=lead,
                year=year,
                date=slot_date,
                lesson_number=value("lesson_number"),
                exclude_pk=self.instance.pk if self.instance else None,
            )
            if busy is not None:
                api_error(
                    Codes.SLOT_NUMBER_TAKEN,
                    services.occupied_message(
                        slot_date, value("lesson_number"), busy.course.name
                    ),
                    field="lesson_number",
                    date=str(slot_date),
                    number=value("lesson_number"),
                    class_name=busy.course.name,
                )

        attrs["year"] = year
        return attrs


class SlotMoveSerializer(serializers.Serializer):
    """
    Куда переносится занятие, каким образом — и почему.

    Причина необязательна на уровне API, но интерфейс её подставляет: на
    календарной оси перенос обязан оставить след, а след без объяснения
    через полгода не прочитать. Само занятие в теле не называется — оно в
    адресе.

    **Режимов два, и это два разных события.** `once` — сорвался час: он
    остаётся отменённым с причиной, а на новом месте появляется
    дополнительный. `series` — изменилось расписание: ряд (тот же день
    недели, тот же номер) переезжает с этого часа и до конца года, и ни
    отмены, ни дополнительных при этом не возникает, потому что срыва не
    было. Умолчание — `once`: разовый перенос случается чаще, и молчащий
    клиент должен получить то же, что получал всегда.

    Причина у `series` не спрашивается вовсе: отменять нечего, а поле,
    которое некуда записать, обещало бы след, которого не будет.
    """

    ONCE = "once"
    SERIES = "series"

    date = serializers.DateField()
    lesson_number = serializers.IntegerField(
        min_value=1, max_value=MAX_LESSON_NUMBER
    )
    mode = serializers.ChoiceField(choices=(ONCE, SERIES), default=ONCE)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


from plans.models import PlanNode


class AttendanceMarkSerializer(serializers.Serializer):
    """Одна отметка: кто и как. `status: null` снимает её."""

    student = serializers.IntegerField()
    status = serializers.ChoiceField(
        choices=Attendance.Status.choices, allow_null=True
    )
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)


class AttendanceSerializer(serializers.Serializer):
    """
    Журнал занятия набором, а не по одному.

    Класс отмечают за один взгляд: запрос на человека превратил бы это в
    двадцать запросов и в двадцать возможностей отметить половину.
    """

    marks = AttendanceMarkSerializer(many=True, allow_empty=False)

    def validate_marks(self, marks):
        """
        Отмечают только тех, кто в курсе. Снятого — тоже: он мог быть на
        занятии до того, как его сняли, и отметка за тот день настоящая.
        """
        course = self.context["course"]
        enrolled = set(
            CourseStudent.objects.filter(course=course).values_list(
                "student_id", flat=True
            )
        )
        outsiders = [row["student"] for row in marks if row["student"] not in enrolled]
        if outsiders:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That student does not study in this course.",
                field="marks",
            )

        return marks


class ClosedSlotSerializer(serializers.Serializer):
    """Одна строка закрытия: что прошло — или что занятия не было."""

    slot = serializers.IntegerField()
    lesson = serializers.PrimaryKeyRelatedField(
        queryset=PlanNode.objects.none(), required=False, allow_null=True
    )
    cancelled = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def get_fields(self):
        fields = super().get_fields()
        # только уроки своих курсов и только уроки: тему не проходят
        fields["lesson"].queryset = PlanNode.objects.filter(
            course__in=teacher_courses(self), is_section=False
        )
        return fields


class CloseDaySerializer(serializers.Serializer):
    """
    Закрытие долгов пачкой.

    Пачкой — потому что вернувшийся из отпуска иначе не станет отмечать
    вовсе; с просмотром — потому что «отметить всё не глядя» превращает
    запись в формальность, а формально заполненное поле хуже вычисленного:
    оно выглядит фактом.
    """

    closed = ClosedSlotSerializer(many=True, allow_empty=False)


class CopySerializer(serializers.Serializer):
    """
    Input for /api/lessons/copy/.

    Without `course_id` the whole schedule is copied — every course this
    teacher works in whose year touches the target period.
    """

    course_id = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.none(),
        source="course",
        required=False,
        allow_null=True,
    )
    source_start = serializers.DateField()
    source_end = serializers.DateField()
    target_start = serializers.DateField()
    target_end = serializers.DateField()
    mode = serializers.ChoiceField(choices=("replace", "merge"), default="merge")
    # «через неделю»: у курса, который идёт раз в две недели, копирование
    # каждой недели рисовало вдвое больше уроков, чем бывает
    step = serializers.ChoiceField(choices=(1, 2), default=1)

    def get_fields(self):
        fields = super().get_fields()
        fields["course_id"].queryset = school_courses(self)
        return fields

    def validate(self, attrs):
        for start, end in (("source_start", "source_end"), ("target_start", "target_end")):
            if attrs[end] < attrs[start]:
                api_error(
                    Codes.PERIOD_REVERSED,
                    "The end date is earlier than the start date.",
                    field=end,
                )
        return attrs


class RepeatSerializer(serializers.Serializer):
    """
    Урок и его повторы: вход для /api/slots/repeat/.

    Сетку строят рядами, а не клетками: «вторник, третий час, до конца
    года» — одно решение, а не тридцать четыре. Раньше это делалось
    копированием недели, то есть сначала нарисуй неделю, потом раскатай, —
    и ради одного добавленного часа приходилось копировать всё подряд,
    натыкаясь на уже занятые места.

    Граница спрашивается, а не подразумевается: конец года подставлен по
    умолчанию, но четверть, полугодие и «до Нового года» встречаются не
    реже.
    """

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    date = serializers.DateField()
    lesson_number = serializers.IntegerField(
        min_value=1, max_value=MAX_LESSON_NUMBER
    )
    # «через неделю» — то же деление, что у копирования периода: курс,
    # который идёт раз в две недели, иначе рисуется вдвое чаще, чем бывает
    step = serializers.ChoiceField(choices=(1, 2), default=1)
    until = serializers.DateField()
    # Кабинет — свойство **ряда**, а не одной его клетки. Спрашивается он в
    # том же окне, что и повтор, и молча терялся: у ряда поля не было вовсе,
    # так что «вторник, третий час, 214, до конца года» заводило тридцать
    # четыре часа без кабинета — и проставлять его приходилось по одному.
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.none(), required=False, allow_null=True
    )

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        fields["room"].queryset = school_rooms(self)
        return fields

    def validate(self, attrs):
        if attrs["until"] < attrs["date"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="until",
            )
        return attrs


class PeriodSerializer(serializers.Serializer):
    """Period boundaries for /api/lessons/agenda/."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs


class BulkDeleteSerializer(serializers.Serializer):
    """
    Массовое удаление: приходит query-параметрами.

    Сверх периода — два необязательных сужения, и вместе они и есть «ряд»:
    день недели и номер урока. Сетку строят рядами («вторник, третий час,
    до конца года»), и разбирают её так же: ошиблись рядом — убрали ряд, а
    не весь период, в котором стоит ещё десяток чужих часов.

    Второго эндпоинта ради этого не завели: путь массового удаления один, и
    два разных счёта того, что уходит, разошлись бы молча.
    """

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    start = serializers.DateField()
    end = serializers.DateField()
    # 0 — понедельник, как в `date.weekday()` и во всём остальном проекте
    weekday = serializers.IntegerField(
        min_value=0, max_value=6, required=False, allow_null=True
    )
    lesson_number = serializers.IntegerField(
        min_value=1, max_value=MAX_LESSON_NUMBER, required=False, allow_null=True
    )
    only_regular = serializers.BooleanField(default=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        return fields

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs


class CourseStudentSerializer(serializers.ModelSerializer):
    """
    Кто учится на курсе. Форма та же, что у назначения и методиста.

    Снятый с курса из списка не исчезает — у него стоит `removed_at`, и
    интерфейс показывает его отдельно: он всё ещё видит своё прошлое в
    курсе, и вернуть его нужно уметь той же кнопкой.
    """

    student_name = serializers.SerializerMethodField()
    student_email = serializers.CharField(source="student.email", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    active = serializers.BooleanField(source="is_active", read_only=True)
    # «ещё не входил» — не своё поле, а `last_login`: он пуст ровно до
    # первого входа и ничего для этого не требует
    arrived = serializers.SerializerMethodField()

    class Meta:
        model = CourseStudent
        fields = (
            "id",
            "course",
            "student",
            "student_name",
            "student_email",
            "course_name",
            "active",
            "arrived",
            "created_at",
            "removed_at",
        )
        read_only_fields = ("created_at", "removed_at")
        # уникальность пары DRF выводит из модели сам, и она здесь мешает:
        # повторное зачисление той же пары означает «верните снятого», а не
        # «такая строка уже есть». Возврат делает вьюха, строка одна и та же
        validators = []

    def get_student_name(self, row) -> str:
        return full_name(row.student)

    def get_arrived(self, row) -> bool:
        return row.student.last_login is not None

    def get_fields(self):
        fields = super().get_fields()
        school_id = getattr(self.context.get("request").user, "school_id", None)
        fields["course"].queryset = Course.objects.filter(school_id=school_id)
        # только ученики своей школы: учителя здесь не бывает по построению,
        # а чужой id так же не существует, как и несуществующий
        fields["student"].queryset = get_user_model().objects.filter(
            school_id=school_id, kind=get_user_model().Kind.STUDENT
        )
        return fields


class CourseMethodistSerializer(serializers.ModelSerializer):
    """Кто утверждает план курса: та же форма, что у назначения учителя."""

    user_name = serializers.SerializerMethodField()
    course_name = serializers.CharField(source="course.name", read_only=True)

    class Meta:
        model = CourseMethodist
        fields = ("id", "course", "user", "user_name", "course_name", "created_at")
        read_only_fields = ("created_at",)
        validators = [
            UniqueTogetherValidator(
                queryset=CourseMethodist.objects.all(),
                fields=("course", "user"),
                message="This person already approves the plan of this course.",
            ),
        ]

    def get_user_name(self, row) -> str:
        return full_name(row.user)

    def get_fields(self):
        fields = super().get_fields()
        school_id = getattr(self.context.get("request").user, "school_id", None)
        # курс и человек — только свои: чужой id так же не существует, как и
        # несуществующий
        fields["course"].queryset = Course.objects.filter(school_id=school_id)
        fields["user"].queryset = get_user_model().objects.filter(
            school_id=school_id
        )
        return fields


class BellSerializer(serializers.Serializer):
    """Одна строка звонков: номер урока и его границы."""

    number = serializers.IntegerField(min_value=1, max_value=MAX_LESSON_NUMBER)
    starts_at = serializers.TimeField()
    ends_at = serializers.TimeField()


class BellsSerializer(serializers.Serializer):
    """
    Расписание звонков целиком. Пустой список — «звонков нет», это законно.

    Проверяется здесь то, чего не выразить ограничением строки: номер не
    повторяется и урок не кончается раньше начала. Второе стоит и в базе —
    отрицательная перемена ломает не показ, а расчёты по нему, — но сказать об
    этом человеку словами должен сервер, а не пятисотка от Postgres.
    """

    bells = BellSerializer(many=True)

    def validate_bells(self, value):
        numbers = [one["number"] for one in value]
        if len(numbers) != len(set(numbers)):
            api_error(
                Codes.BELL_NUMBER_TWICE,
                "Each lesson number appears once.",
                field="bells",
            )
        for one in value:
            if one["ends_at"] <= one["starts_at"]:
                api_error(
                    Codes.BELL_ENDS_BEFORE_IT_STARTS,
                    "A lesson ends after it starts.",
                    field="bells",
                    number=one["number"],
                )
        return value
