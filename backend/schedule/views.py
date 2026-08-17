from collections import defaultdict
from datetime import timedelta

from calendars import services as calendar_services
from calendars.models import SchoolYear
from config.access import (
    IsCourseTeacherOrSchoolAdmin,
    allowed_to_write_schedule,
    IsSchoolMember,
    IsStudent,
    IsTeacher,
    SchoolScopedViewSet,
    require_schedule_write,
)
from config.errors import Codes, api_denied, api_error
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from files.models import Attachment
from plans.models import PlanNode
from plans import services as plan_services

from . import services
from .services import sweepable
from schools import roster, services as school_services

from .models import (
    Course,
    CourseAssignment,
    CourseMethodist,
    CourseStudent,
    GradeLevel,
    Slot,
    Subject,
)
from .serializers import (
    AttendanceSerializer,
    BulkDeleteSerializer,
    CloseDaySerializer,
    CourseMethodistSerializer,
    CourseStudentSerializer,
    SubjectSerializer,
    CopySerializer,
    CourseAssignmentSerializer,
    CourseSerializer,
    GradeLevelSerializer,
    SlotMoveSerializer,
    SlotSerializer,
    PeriodSerializer,
    full_name,
)


# «add years 1..N»: the two buttons of the empty state offer 11 and 13, and
# the field accepts anything up to this — a school with more years than that
# is not a school we can guess about anyway
PRESET_MAX = 20


def read_date(value):
    """A date from a query parameter. Garbage is None, not a 500."""
    try:
        return parse_date(value or "")
    except ValueError:
        # parse_date raises on «2026-13-45»: the shape fits, the date does not
        return None


class SubjectViewSet(SchoolScopedViewSet):
    """
    The school's list of subjects: «Алгебра», «Геометрия».

    Everybody reads it — a teacher searching the library needs the names —
    and administrators keep it, like the courses next to it.
    """

    serializer_class = SubjectSerializer
    queryset = Subject.objects.annotate(course_count=Count("courses"))

    def perform_destroy(self, instance):
        """A subject a course still points at stays: PROTECT says so."""
        try:
            instance.delete()
        except ProtectedError:
            api_error(
                Codes.SUBJECT_IN_USE,
                f"«{instance.name}» is used by {instance.courses.count()} courses.",
                name=instance.name,
                courses=instance.courses.count(),
            )


class GradeLevelViewSet(SchoolScopedViewSet):
    """
    The school's year groups: «Grade 6», «MYP 4», «10 класс».

    Kept by administrators, read by everybody — the course form offers them
    and the library searches on them.
    """

    serializer_class = GradeLevelSerializer
    queryset = GradeLevel.objects.annotate(course_count=Count("courses"))

    def perform_destroy(self, instance):
        """A level a course still points at stays: PROTECT says so."""
        try:
            instance.delete()
        except ProtectedError:
            api_error(
                Codes.GRADE_IN_USE,
                f"«{instance.name}» is used by {instance.courses.count()} courses.",
                name=instance.name,
                courses=instance.courses.count(),
            )

    @action(detail=False, methods=["post"])
    def preset(self, request):
        """
        Fill the list with years 1..N in one go.

        A school with no year groups cannot have a course, so the empty state
        offers this instead of eleven rows nobody asked for. Existing levels
        are left alone — the button adds what is missing and nothing else,
        which also makes it safe to press twice.
        """
        self.check_admin()
        through = request.data.get("through")

        if not str(through).isdigit() or not 1 <= int(through) <= PRESET_MAX:
            api_error(
                Codes.GRADE_PRESET_INVALID,
                f"«through» must be a number between 1 and {PRESET_MAX}.",
                field="through",
                limit=PRESET_MAX,
            )

        through = int(through)
        school = request.user.school
        known = set(
            GradeLevel.objects.filter(school=school).values_list("level", flat=True)
        )
        created = GradeLevel.objects.bulk_create(
            GradeLevel(
                school=school,
                level=level,
                name=services.grade_name(level, request.user.language),
            )
            for level in range(1, through + 1)
            if level not in known
        )

        return Response({"created": len(created)}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["delete"], url_path="unused")
    def delete_unused(self, request):
        """
        Clear out the year groups no course points at.

        The counterpart of the preset button: pressing «1–13» in a school
        that turns out to use four of them should not mean nine confirmations
        one after another. What is in use cannot be reached by this — the
        filter is the same `courses` count the list already shows.
        """
        self.check_admin()
        doomed = self.get_queryset().filter(courses__isnull=True)
        names = list(doomed.values_list("name", flat=True))
        doomed.delete()

        return Response({"deleted": len(names), "names": names})

    def check_admin(self):
        """
        The role check the extra actions need.

        `IsSchoolAdminForWrite` looks at the HTTP method, and both actions
        below are writes wearing POST and DELETE — but DRF checks permissions
        before it knows which action is running, and `preset` is a POST to a
        list route, which the class already covers. This keeps the two paths
        honest even if that ever changes.
        """
        if not self.request.user.is_school_admin:
            api_denied(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator may change the reference lists.",
            )


class CourseMethodistViewSet(SchoolScopedViewSet):
    """
    Кто утверждает план курса.

    Устроено как назначение учителя рядом: та же пара «курс и человек», тот
    же администратор. Разница в вопросе — «кто ведёт» против «кто
    утверждает», — и на карточке курса они стоят двумя строками.
    """

    serializer_class = CourseMethodistSerializer
    queryset = CourseMethodist.objects.select_related("course", "user")
    school_path = "course__school"

    def get_queryset(self):
        queryset = super().get_queryset()
        course = self.request.query_params.get("course")
        if course:
            queryset = (
                queryset.filter(course_id=course)
                if course.isdigit()
                else queryset.none()
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class CourseStudentViewSet(SchoolScopedViewSet):
    """
    Состав курса. Ставит и снимает администратор, как и всё школьное.

    Снятие **не удаляет строку**: ученик перестаёт работать в курсе, но
    продолжает видеть, что уже сделал, и строка — это и есть его право
    читать. Повторный `POST` той же пары возвращает снятого: пара одна и та
    же навсегда.
    """

    serializer_class = CourseStudentSerializer
    queryset = CourseStudent.objects.select_related("course", "student")
    school_path = "course__school"

    def get_queryset(self):
        queryset = super().get_queryset()
        course = self.request.query_params.get("course")
        if course:
            queryset = (
                queryset.filter(course_id=course)
                if course.isdigit()
                else queryset.none()
            )

        return queryset

    def create(self, request, *args, **kwargs):
        """Зачислить — или вернуть снятого той же строкой."""
        form = self.get_serializer(data=request.data)
        form.is_valid(raise_exception=True)
        row = school_services.enrol(
            form.validated_data["student"],
            form.validated_data["course"],
            by=request.user,
        )

        return Response(
            self.get_serializer(row).data, status=status.HTTP_201_CREATED
        )

    def perform_destroy(self, instance):
        school_services.remove_from_course(instance)

    # --- список класса, вставленный целиком ------------------------------------

    def requested_course(self):
        """Курс из `?course=`, только своей школы: чужой — 404."""
        raw = self.request.query_params.get("course")
        if not raw or not raw.isdigit():
            api_error(
                Codes.CLASS_REQUIRED,
                "The «course» query parameter with a course id is required.",
                field="course",
            )

        return get_object_or_404(
            Course.objects.filter(school_id=self.request.user.school_id), pk=raw
        )

    @action(detail=False, methods=["post"])
    def preview(self, request):
        """
        Что сделает вставка — не делая ничего.

        **Ни от чего не отказывается**, включая нечитаемый текст: ошибки
        приезжают списком в теле, как у предпросмотра плана. Иначе
        единственным следом отказа была бы ошибка в консоли браузера — окно
        показывает список, а кодов HTTP не разбирает.
        """
        course = self.requested_course()
        parsed = roster.parse_roster(request.data.get("text") or "")
        decisions = roster.plan_roster(parsed.people, course)

        return Response(roster.payload(parsed, decisions))

    @action(detail=False, methods=["post"])
    def enrol(self, request):
        """
        Применить вставку — одной транзакцией.

        Отказ целиком остаётся за ошибками разбора: там непонятно, что
        имелось в виду, и половина применённого списка хуже неприменённого.
        Занятый адрес — другое дело: про него сказано поимённо и заранее, а
        остальные двадцать девять человек ни в чём не виноваты.
        """
        course = self.requested_course()
        parsed = roster.parse_roster(request.data.get("text") or "")

        if parsed.errors:
            first = parsed.errors[0]
            api_error(first["code"], first["detail"], field="text", **first["params"])

        if not parsed.people:
            api_error(
                Codes.ROSTER_EMPTY,
                "There is not a single address in what was pasted.",
                field="text",
            )

        decisions = roster.plan_roster(parsed.people, course)
        roster.apply_roster(decisions, course, by=request.user)

        return Response(roster.payload(parsed, decisions))


class StudentCoursesView(APIView):
    """
    Курсы ученика: где он учится и где учился.

    Два списка, а не один. Снятый с курса продолжает видеть, что уже
    сделал, — и должен понимать, почему курс уехал вниз и почему в нём
    ничего не нажимается. Курс, исчезнувший без объяснения, читается как
    поломка.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def get(self, request):
        rows = (
            # только курсы своей школы: строки прошлой школы остаются в базе
            # — они след того, что человек там учился, — но в его списке им
            # места нет
            CourseStudent.objects.filter(
                student=request.user, course__school_id=request.user.school_id
            )
            .select_related("course", "course__subject", "course__grade")
            # активные сверху: снятые уезжают вниз, как их и показывают
            .order_by(F("removed_at").asc(nulls_first=True), "course__name")
        )

        return Response(
            {
                "courses": [
                    {
                        "id": row.course_id,
                        "name": row.course.name,
                        "subject": row.course.subject.name if row.course.subject else None,
                        "grade": row.course.grade.name if row.course.grade else None,
                        "active": row.is_active,
                    }
                    for row in rows
                ]
            }
        )


class CourseAssignmentViewSet(SchoolScopedViewSet):
    """
    Who teaches which course.

    Written from two sides — the teacher's card and the course's card — and
    that is the point of having one table: the question is the same, but
    which end somebody starts from depends on what they are thinking about.
    """

    serializer_class = CourseAssignmentSerializer
    queryset = CourseAssignment.objects.select_related("course", "teacher")
    school_path = "course__school"

    def get_queryset(self):
        queryset = super().get_queryset()

        for param, lookup in (("course", "course_id"), ("teacher", "teacher_id")):
            value = self.request.query_params.get(param)
            if value:
                queryset = (
                    queryset.filter(**{lookup: value})
                    if value.isdigit()
                    else queryset.none()
                )

        return queryset

    def perform_destroy(self, instance):
        """
        Забрать у человека курс. Работа при этом никуда не девается.

        Раньше подтверждение спрашивали потому, что снятие грозило чужой
        работой: расписание, план и контрольные были личными. Теперь они
        принадлежат курсу и достаются следующему ведущему целиком, — а
        подтверждение осталось, потому что осталось другое последствие:
        **курс пропадёт из списков этого человека**. `Course.objects
        .for_teacher` — это назначенные, и только они.

        Поэтому первый DELETE отвечает счётчиками: вот сколько всего в
        курсе и вот кто перестанет это видеть. `?force=true` подтверждает.
        """
        slots = Slot.objects.filter(course=instance.course).count()
        rows = PlanNode.objects.filter(course=instance.course).count()
        works = instance.course.works.count()

        # всё перечисленное принадлежит **курсу** и достаётся следующему
        # ведущему целиком; названо оно затем, чтобы это было видно до
        # нажатия, а не затем, чтобы кого-то остановить
        forced = self.request.query_params.get("force", "").lower() == "true"
        if (slots or rows or works) and not forced:
            api_error(
                Codes.ASSIGNMENT_IN_USE,
                f"«{instance.course.name}» keeps its {slots} lessons, {rows} "
                f"plan rows and {works} assignments — nothing is deleted, they "
                f"belong to the course. But {full_name(instance.teacher)} will "
                "stop seeing the course at all; repeat with force=true to confirm.",
                teacher=full_name(instance.teacher),
                course=instance.course.name,
                slots=slots,
                plan_rows=rows,
                works=works,
            )

        instance.delete()


class CourseViewSet(SchoolScopedViewSet):
    """
    The school's courses. The list is filtered by ?year=<id>.

    By default a teacher gets **their own** courses — the ones they are
    assigned to (see `Course.objects.for_teacher`). `?scope=school` asks for
    the whole list instead, which is what the «School» section shows; it is
    not a secret from anybody, the school timetable names every course
    anyway.

    Every teacher reads; only an administrator creates, renames and deletes.
    """

    serializer_class = CourseSerializer
    queryset = Course.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        # only the list narrows: a course reached by id is a school object
        # like any other, and an administrator edits the ones they do not
        # teach — which is most of them
        if self.action == "list" and self.request.query_params.get("scope") != "school":
            queryset = queryset.filter(
                pk__in=Course.objects.for_teacher(self.request.user)
            )

        year = self.request.query_params.get("year")
        if year:
            # a non-numeric value must not blow up on a cast
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return (
            queryset.select_related("year", "subject", "grade")
            .prefetch_related("assignments__teacher")
            .annotate(
                active_students=Count(
                    "students",
                    filter=Q(students__removed_at__isnull=True),
                    distinct=True,
                )
            )
            # группировка стирает порядок из Meta — тот же самый, но теперь
            # его надо назвать вслух, иначе курсы едут как попало
            .order_by(*Course._meta.ordering)
        )

    def perform_destroy(self, instance):
        """
        Deleting a course that somebody teaches is refused, not cascaded.

        The slots, the plan rows and the works hold it under PROTECT — an
        administrator must not wipe a colleague's year with one button. The
        answer says how much is in the way and whose it is.
        """
        try:
            instance.delete()
        except ProtectedError:
            slots = instance.slots.count()
            rows = instance.plan_nodes.count()
            works = instance.works.count()
            # кто ведёт — один человек, и всё перечисленное теперь его: план,
            # расписание и работы принадлежат курсу целиком
            teachers = sorted(
                str(name or email)
                for name, email in instance.assignments.values_list(
                    "teacher__first_name", "teacher__email"
                )
            )
            api_error(
                Codes.COURSE_IN_USE,
                f"«{instance.name}» is in use: {rows} plan rows, {slots} "
                f"lessons and {works} assignments. "
                f"Ask {', '.join(teachers) or 'its teacher'} to clear it first.",
                name=instance.name,
                slots=slots,
                plan_rows=rows,
                works=works,
                teachers=teachers,
            )


class SlotViewSet(SchoolScopedViewSet):
    """
    Расписание. Одно на всех: и «моё расписание», и расписание школы.

    Отдельной таблицы у школьного расписания больше нет. `MasterSlot` был
    ровно этим же — курс, дата, номер, — и после того, как расписание
    переехало на курс, у него не осталось ни одного своего поля: школа
    выводится из курса, учитель — из назначения. Две таблицы с одним ключом
    расходятся молча, и разошлись бы: проверки занятости смотрели каждая в
    свою и друг друга не видели.

    Отсюда форма доступа, которой больше нет ни у чего: **читает вся школа**
    (иначе не существует экрана «Расписание школы»), **пишет ведущий курса
    или администратор** (`IsCourseTeacherOrSchoolAdmin`). Расписание
    одновременно общий артефакт школы и содержимое курса, и обе половины
    настоящие.

    Список по умолчанию отдаёт **свои** уроки, `?scope=school` — все, тем же
    приёмом, что у курсов: «Моё расписание» иначе стало бы расписанием
    школы. Фильтры — `course`, `teacher`, `start`, `end`; сверх CRUD
    массовые операции: copy, bulk, stats и summary.
    """

    serializer_class = SlotSerializer
    queryset = Slot.objects.all()
    school_path = "course__school"
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsCourseTeacherOrSchoolAdmin,
    ]

    def my_courses(self):
        return Course.objects.for_teacher(self.request.user)

    def own_slots(self):
        """Уроки моих курсов — то, что человек называет своим расписанием."""
        return Slot.objects.filter(course__in=self.my_courses())

    def require_write(self, course):
        """
        Право на запись там, где объекта на входе нет: курс приходит в теле.

        `has_object_permission` закрывает адреса с id, а создание, копирование
        и массовое удаление называют курс сами — и мимо неё проходят.
        """
        require_schedule_write(self.request.user, course)

    def perform_create(self, serializer):
        self.require_write(serializer.validated_data["course"])
        serializer.save()

    def get_queryset(self):
        queryset = super().get_queryset().select_related("course", "year")
        # year.periods() нужен каждому слоту для предупреждения о неучебном
        # дне, назначение — чтобы сказать, кто ведёт: и то и другое одним
        # запросом на всю выборку, а не на строку
        queryset = queryset.prefetch_related(
            "year__exceptions", "course__assignments__teacher"
        )

        params = self.request.query_params
        # по умолчанию свои: список — это «Моё расписание», и школьный вид
        # спрашивает всё явно
        if self.action == "list" and params.get("scope") != "school":
            queryset = queryset.filter(course__in=self.my_courses())

        teacher = params.get("teacher")
        if teacher:
            queryset = (
                queryset.filter(course__assignments__teacher_id=teacher)
                if teacher.isdigit()
                else queryset.none()
            )

        year = params.get("year")
        if year:
            queryset = (
                queryset.filter(year_id=year) if year.isdigit() else queryset.none()
            )

        class_id = params.get("course")
        if class_id:
            queryset = (
                queryset.filter(course_id=class_id)
                if class_id.isdigit()
                else queryset.none()
            )

        for param, lookup in (("start", "date__gte"), ("end", "date__lte")):
            raw = params.get(param)
            if not raw:
                continue
            # мусор в параметре не должен превращаться в 500
            parsed = read_date(raw)
            queryset = queryset.filter(**{lookup: parsed}) if parsed else queryset.none()

        return queryset

    def copy_one_course(self, course, data, study_dates):
        """
        Копирование одного курса. Внутри транзакции вызывающего: уроки,
        созданные предыдущему курсу, занимают номера для следующего.

        Выборки идут по **курсу**, а не «по своим»: тот же код обслуживает и
        учителя, копирующего свою неделю, и администратора, раскатывающего
        сетку на год. Право спрошено выше, у `copy`.
        """
        target = (data["target_start"], data["target_end"])
        year = course.year

        source_numbers = defaultdict(list)
        source_slots = Slot.objects.filter(
            course=course,
            date__range=(data["source_start"], data["source_end"]),
            is_extra=False,
            is_cancelled=False,
        )
        for slot in source_slots:
            source_numbers[slot.date].append(slot.lesson_number)

        plan, skipped = services.plan_copy(
            source_start=data["source_start"],
            source_end=data["source_end"],
            target_start=data["target_start"],
            target_end=data["target_end"],
            source_numbers=source_numbers,
            study_dates=study_dates,
        )

        deleted = 0
        if data["mode"] == "replace":
            # заменяются только пустые клетки сетки. Отмена с причиной,
            # дополнительный урок, отметка «что прошли», замена и заданная
            # работа — всё это записи о том, что было, и массовая операция
            # их не трогает. Администратора правило касается тем более: он
            # раскатывает сетку на весь год и стёр бы чужую историю разом
            deleted, _ = sweepable(
                Slot.objects.filter(course=course, date__range=target)
            ).delete()

        occupied = set(
            Slot.objects.filter(course=course, date__range=target)
            .values_list("date", "lesson_number")
        )

        # номера, уже занятые другими курсами **того же учителя**: двух
        # уроков разом не бывает, поэтому такие слоты пропускаются с отчётом.
        # Учитель тут — ведущий копируемого курса, а не тот, кто нажал:
        # администратор раскатывает чужую сетку, и мешать ей может только
        # чужое же расписание. У курса без ведущего мешать нечему
        lead = CourseAssignment.objects.filter(course=course).values_list(
            "teacher_id", flat=True
        ).first()
        busy = {}
        if lead is not None:
            busy = {
                (slot.date, slot.lesson_number): slot.course.name
                for slot in Slot.objects.filter(
                    course__assignments__teacher_id=lead,
                    year=year,
                    date__range=target,
                    is_cancelled=False,
                )
                .exclude(course=course)
                .select_related("course")
            }

        result = services.place_copies(
            plan=plan,
            skipped=skipped,
            occupied=occupied,
            busy=busy,
            make=lambda day, number: Slot(
                year=year,
                course=course,
                date=day,
                lesson_number=number,
            ),
        )
        Slot.objects.bulk_create(result["created"])

        return {
            "created": len(result["created"]),
            "skipped": result["skipped"],
            "deleted": deleted,
            "conflicts": result["conflicts"],
        }

    @action(detail=False, methods=["post"])
    def copy(self, request):
        """
        Повторить раскладку одного периода на другом.

        Без `course_id` едет расписание целиком — все курсы, которые
        спрашивающий вправе править и чей год задевает цель: у учителя это
        его курсы, у администратора вся школа. Отменённые и дополнительные
        уроки не копируются ни в одном режиме.
        """
        form = CopySerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        data = form.validated_data

        one = data.get("course")
        if one is not None:
            courses = [one]
        else:
            mine = (
                Course.objects.filter(school_id=request.user.school_id)
                if request.user.is_school_admin
                else Course.objects.for_teacher(request.user)
            )
            courses = list(
                mine.filter(
                    year__start_date__lte=data["target_end"],
                    year__end_date__gte=data["target_start"],
                ).select_related("year")
            )

        totals = {"created": 0, "skipped": 0, "deleted": 0, "conflicts": []}
        study_by_year = {}

        with transaction.atomic():
            for course in courses:
                self.require_write(course)
                year = course.year
                if year.pk not in study_by_year:
                    # study days are calendars' business — we only ask
                    study_by_year[year.pk] = {
                        day.date for day in year.build_days() if day.is_study
                    }

                result = self.copy_one_course(course, data, study_by_year[year.pk])
                for key in ("created", "skipped", "deleted"):
                    totals[key] += result[key]
                totals["conflicts"].extend(result["conflicts"])

        return Response(totals)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """
        Перенести занятие на другую дату — одно движение, две записи.

        Соблазнительно просто переписать дату: занятие то же, урок тот же,
        связь едет следом. Но перенос — событие **календарной** оси, и
        именно её читает администрация: «сколько часов сорвано и всё ли
        закрыто». С переписанной датой к концу года выходит идеально ровная
        картина, в которой не было ни одного срыва, — а их было двенадцать,
        и каждый чем-то компенсировали.

        Поэтому старое место остаётся отменённым с причиной, новое
        появляется дополнительным, и плашка «отменено 1 · добавлено 1»
        читается ровно как то, чем это было. Всё, что занятие успело
        накопить, переезжает: что прошли, кто вёл, заданные работы.

        Проверяет цель обычный `SlotSerializer` — границы года, занятость
        номера у ведущего, уникальность: правила переноса не должны быть
        мягче правил создания, а второй список правил разошёлся бы с первым.
        """
        slot = self.get_object()
        form = SlotMoveSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        target = form.validated_data

        if (target["date"], target["lesson_number"]) == (
            slot.date,
            slot.lesson_number,
        ):
            api_error(
                Codes.SLOT_MOVE_SAME_PLACE,
                "The lesson is already at that date and number.",
                field="date",
            )

        arrival = SlotSerializer(
            data={
                "course": slot.course_id,
                "date": target["date"].isoformat(),
                "lesson_number": target["lesson_number"],
                "is_extra": True,
                "lesson": slot.lesson_id,
                "taught_by": slot.taught_by_id,
            },
            context=self.get_serializer_context(),
        )
        # Проверка цели идёт **внутри** транзакции, и это не перестраховка:
        # связь с уроком `OneToOne`, поэтому её надо снять с прежнего часа
        # до того, как её примет новый, — а если цель окажется занята,
        # откат вернёт занятие целиком, вместе со связью.
        with transaction.atomic():
            slot.lesson = None
            slot.save(update_fields=["lesson"])

            arrival.is_valid(raise_exception=True)
            moved = arrival.save()

            # работы задавали на этом занятии, и занятие уехало вместе с ними
            slot.works.update(slot=moved)
            slot.is_cancelled = True
            slot.reason = target.get("reason", "")
            # кто вёл — свойство состоявшегося занятия, а это не состоялось:
            # оно уехало на новую дату вместе со связью
            slot.taught_by = None
            slot.save(update_fields=["is_cancelled", "reason", "taught_by"])

        return Response(arrival.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["delete"])
    def bulk(self, request):
        """Убрать уроки курса за период. Правит тот, кому курс дозволен."""
        params = request.query_params
        form = BulkDeleteSerializer(
            data={
                "course": params.get("course"),
                "start": params.get("start"),
                "end": params.get("end"),
                "only_regular": params.get("only_regular", False),
            },
            context=self.get_serializer_context(),
        )
        form.is_valid(raise_exception=True)
        data = form.validated_data
        self.require_write(data["course"])

        queryset = Slot.objects.filter(
            course=data["course"],
            date__range=(data["start"], data["end"]),
        )
        if data["only_regular"]:
            # всё, что человек отметил руками, переживает массовую чистку
            queryset = sweepable(queryset)

        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        """
        Расписание всех своих курсов за период, одним ответом.

        Lessons are grouped by date, next to the day markup: whether it is a
        study day and what the exception is called. Dates outside every school
        year carry the status «outside».
        """
        form = PeriodSerializer(data=request.query_params)
        form.is_valid(raise_exception=True)
        start, end = form.validated_data["start"], form.validated_data["end"]

        lessons = defaultdict(list)
        slots = (
            self.own_slots()
            .filter(date__range=(start, end))
            .select_related("course")
        )
        for slot in slots:
            lessons[slot.date.isoformat()].append(
                {
                    "id": slot.id,
                    "lesson_number": slot.lesson_number,
                    "course_id": slot.course_id,
                    "course_name": slot.course.name,
                    "is_cancelled": slot.is_cancelled,
                    "is_extra": slot.is_extra,
                    "reason": slot.reason,
                }
            )

        # the markup comes from the calendar: the year knows the breaks, and
        # the payload is the one every endpoint sends — see `day_payload`
        days = {
            day.isoformat(): calendar_services.day_payload(
                calendar_services.outside_day(day)
            )
            for day in calendar_services.iter_dates(start, end)
        }
        years = SchoolYear.objects.filter(
            school_id=request.user.school_id,
            start_date__lte=end,
            end_date__gte=start,
        ).prefetch_related("exceptions")
        for year in years:
            for day in year.build_days():
                if start <= day.date <= end:
                    days[day.date.isoformat()] = calendar_services.day_payload(day)

        return Response({"start": start, "end": end, "lessons": lessons, "days": days})

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """How many lessons there are, past, left, cancelled and extra."""
        queryset = self.own_slots()

        class_id = request.query_params.get("course")
        if class_id:
            queryset = (
                queryset.filter(course_id=class_id)
                if class_id.isdigit()
                else queryset.none()
            )

        today = timezone.localdate()
        # отменённый урок не проведут, поэтому в total он не входит
        live = queryset.filter(is_cancelled=False)
        total = live.count()
        past = live.filter(date__lt=today).count()

        cancelled = queryset.filter(is_cancelled=True)

        return Response(
            {
                "total": total,
                "past": past,
                "remaining": total - past,
                "cancelled": cancelled.count(),
                "extra": live.filter(is_extra=True).count(),
                "cancelled_by_reason": {
                    row["reason"]: row["count"]
                    for row in cancelled.values("reason")
                    .annotate(count=Count("id"))
                    .order_by("-count", "reason")
                },
            }
        )

    @action(detail=True, methods=["get"])
    def card(self, request, pk=None):
        """
        Одно занятие целиком — всё, с чем с ним работают.

        Тот же payload, что в дне, плюс соседи по курсу: экран работы с
        уроком листается по своему курсу, а не по дню, — «что было на
        прошлом» это вопрос про этот же класс, а не про то, что стояло
        следующим часом у другого.

        Своего расчёта здесь нет: содержание из плана, подсказка из той же
        `suggested_topics`, что и на дне. Второй расчёт над теми же данными
        однажды разошёлся бы с первым.

        Списка «с чем ещё можно связать» тут нет и не будет. Что было на
        уроке, решает план: не угадал — правят план, и подсказка меняется
        сама. Выбор из сорока строк отвечал бы на тот же вопрос **мимо**
        плана, не оставляя следа, что он разошёлся с реальностью.
        """
        slot = self.get_object()
        suggested = services.suggested_topics(slot.course)

        neighbours = Slot.objects.filter(course=slot.course).exclude(pk=slot.pk)
        after = (
            neighbours.filter(date__gte=slot.date)
            .exclude(date=slot.date, lesson_number__lt=slot.lesson_number)
            .order_by("date", "lesson_number")
            .values_list("pk", flat=True)
            .first()
        )
        before = (
            neighbours.filter(date__lte=slot.date)
            .exclude(date=slot.date, lesson_number__gt=slot.lesson_number)
            .order_by("-date", "-lesson_number")
            .values_list("pk", flat=True)
            .first()
        )

        card = slot_day_payload(slot, suggested)
        if card["topic"]:
            # вложения строки плана — «материалы урока» на этой странице.
            # В `slot_day_payload` их нет намеренно: он же собирает день, и
            # там это был бы запрос на каждое занятие ради значка
            from files.serializers import AttachmentSerializer, with_sharing

            card["topic"]["attachments"] = AttachmentSerializer(
                with_sharing(Attachment.objects.filter(plan_row_id=card["topic"]["id"])),
                many=True,
            ).data

        return Response(
            {
                **card,
                "date": slot.date,
                "previous": before,
                "next": after,
                # право на правку спрашивается один раз и отдаётся ответом:
                # иначе страница гадала бы о нём по роли, а правило сложнее
                # роли — ведущий курса **или** администратор школы
                "may_write": allowed_to_write_schedule(request.user, slot.course),
                # что мешает записать этот час: очередь без дырок значит,
                # что закрывают их по одной, а экран должен сказать — какую
                # именно, а не просто отказать после нажатия
                # часу не досталось строки плана: слотов больше, чем строк.
                # Это не тупик, а требование — дописать строку, — и сказать
                # об этом должна страница, а не отказ после нажатия
                "needs_row": (
                    slot.lesson_id is None
                    and not slot.is_cancelled
                    and slot.date <= timezone.localdate()
                    and services.suggested_topics(slot.course).get(slot.pk) is None
                ),
                "record_after": (
                    {"id": blocker.pk, "date": blocker.date}
                    if (blocker := record_blocker(slot)) is not None
                    else None
                ),
                # снять можно только последнюю запись курса: у снятия нет
                # следа, и всё, что глубже, было бы правкой прошлого
                "may_withdraw": (
                    slot.lesson_id is not None
                    and (last := Slot.last_record(slot.course)) is not None
                    and last.pk == slot.pk
                ),
            }
        )

    @action(detail=True, methods=["get", "post"])
    def attendance(self, request, pk=None):
        """
        Журнал занятия: кто был, кого не было, кто опоздал.

        Список строится **по составу курса**, а не по отметкам: пока никого
        не отметили, строк в базе нет вовсе, и «не отмечено» отличается от
        «отсутствовал» именно этим. Хранить «не отмечено» значением значило
        бы заводить строку на каждого ученика каждого занятия года.

        Снятые с курса в списке остаются и помечены: их отметки за прошлые
        занятия никуда не делись, а смешивать «не был» и «уже не учится»
        нельзя — это разные ответы.

        POST принимает набор отметок разом (`{"marks": [...]}`), а не по
        одной: отмечают класс за один взгляд, и запрос на человека
        превратил бы это в двадцать запросов. `status: null` снимает
        отметку — строка удаляется, состояние возвращается в «не отмечено».
        """
        slot = self.get_object()

        if request.method == "POST":
            form = AttendanceSerializer(
                data=request.data, context={"course": slot.course}
            )
            form.is_valid(raise_exception=True)
            services.mark_attendance(
                slot, form.validated_data["marks"], by=request.user
            )

        rows = {row.student_id: row for row in slot.attendance.all()}
        enrolled = (
            CourseStudent.objects.filter(course=slot.course)
            .select_related("student")
            .order_by("student__last_name", "student__email")
        )

        return Response(
            {
                "students": [
                    {
                        "id": row.student_id,
                        "name": full_name(row.student),
                        "active": row.removed_at is None,
                        "status": (
                            rows[row.student_id].status
                            if row.student_id in rows
                            else None
                        ),
                        "note": (
                            rows[row.student_id].note if row.student_id in rows else ""
                        ),
                    }
                    for row in enrolled
                ]
            }
        )

    @action(detail=False, methods=["get"])
    def unclosed(self, request):
        """
        Прошедшие занятия своих курсов, за которыми ничего не записано.

        Настойчивость должна стоять **на дороге**, по которой человек и так
        идёт: напоминание сбоку игнорируется на третий день. Поэтому список
        короткий, у каждой строки подставлена тема из раскладки, и закрыть
        его можно одним движением — см. `close` ниже.

        Правила отбора — те же, что у счётчика (`plans.services.record_state`
        и `planLayout.debtSlots` на клиенте), и это важно: число и список за
        ним обязаны говорить одно и то же.

        Срока давности у долга нет: двухнедельная амнистия отменена вместе с
        приходом строгого порядка — при нём дырка не протухает, а блокирует
        следующую запись.
        """
        today = timezone.localdate()

        slots = (
            Slot.objects.filter(
                course__in=self.my_courses(),
                is_cancelled=False,
                date__lte=today,
                lesson__isnull=True,
            )
            .select_related("course")
            .order_by("date", "lesson_number")
        )

        # долг появляется только там, где связь хоть раз ставили: тому, кто
        # кнопкой не пользуется, каждый прошедший час был бы «долгом»
        started = set(
            Slot.objects.filter(
                course__in=self.my_courses(), lesson__isnull=False
            ).values_list("course_id", flat=True)
        )
        slots = [slot for slot in slots if slot.course_id in started]

        suggested = {}
        for course in {slot.course for slot in slots}:
            suggested.update(services.suggested_topics(course))

        return Response(
            {
                "slots": [
                    {
                        "id": slot.pk,
                        "course": {"id": slot.course_id, "name": slot.course.name},
                        "date": slot.date,
                        "lesson_number": slot.lesson_number,
                        "topic": (
                            {"id": topic.pk, "title": topic.title}
                            if (topic := suggested.get(slot.pk))
                            else None
                        ),
                    }
                    for slot in slots
                ]
            }
        )

    @action(detail=False, methods=["post"])
    def close(self, request):
        """
        Закрыть долги пачкой — но с просмотром, а не «отметить всё».

        Вернувшийся из отпуска обязан иметь возможность закрыть пять дней
        разом: заставлять открывать каждый день по одному значит не получить
        отметок вовсе. Но подставленные темы при этом на экране, и разница
        именно в этом: «подтвердить пять предложений» — не то же, что
        «отметить всё не глядя».

        Каждая строка — либо «прошли вот это» (`lesson`), либо «занятия не
        было» (`cancelled` с причиной). Одной транзакцией: половина
        закрытого списка хуже незакрытого, потому что непонятно, какая
        половина.
        """
        form = CloseDaySerializer(
            data=request.data, context=self.get_serializer_context()
        )
        form.is_valid(raise_exception=True)
        rows = form.validated_data["closed"]

        mine = {
            slot.pk: slot
            for slot in Slot.objects.filter(
                pk__in=[row["slot"] for row in rows], course__in=self.my_courses()
            )
        }

        with transaction.atomic():
            for row in rows:
                slot = mine.get(row["slot"])
                if slot is None:
                    api_error(
                        Codes.SLOT_NOT_MINE,
                        "That lesson belongs to a course you do not teach.",
                        field="closed",
                    )

                if row.get("cancelled"):
                    slot.is_cancelled = True
                    slot.reason = row.get("reason", "")
                    slot.save(update_fields=["is_cancelled", "reason"])
                    continue

                node = row.get("lesson")
                if node is None or node.course_id != slot.course_id:
                    api_error(
                        Codes.PARENT_OTHER_CLASS,
                        "That plan lesson belongs to another course.",
                        field="closed",
                    )
                slot.lesson = node
                slot.save(update_fields=["lesson"])

        return Response({"closed": len(rows)})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Сводка по расписанию школы: сколько разложено и у чего нет ведущего.

        «Нагрузка не распределена» раньше выражалась строкой без учителя;
        теперь это уроки курса, на который никого не назначили, — то же самое
        состояние, только без своего поля.
        """
        queryset = Slot.objects.filter(
            course__school_id=request.user.school_id
        )

        year = request.query_params.get("year")
        if year:
            queryset = (
                queryset.filter(year_id=year) if year.isdigit() else queryset.none()
            )

        return Response(
            {
                "total": queryset.count(),
                "unassigned": queryset.filter(course__assignments=None).count(),
                "teachers": queryset.exclude(course__assignments=None)
                .values("course__assignments__teacher_id")
                .distinct()
                .count(),
            }
        )


def record_blocker(slot):
    """
    Час, который надо закрыть раньше этого, — или `None`.

    Экран спрашивает не «можно ли», а «что мешает»: отказ после нажатия
    объясняет то же самое, но уже задним числом, а тут кнопки просто нет и
    рядом написано, куда идти.
    """
    if slot.lesson_id is not None or slot.is_cancelled:
        return None

    nxt = Slot.next_unclosed(slot.course, timezone.localdate())
    return nxt if nxt is not None and nxt.pk != slot.pk else None


def slot_day_payload(slot, suggested) -> dict:
    """
    Одно занятие целиком: содержание, работы и что прошли.

    Содержание берётся у той строки плана, которую **записали**; не
    записали — у подсказанной раскладкой. `confirmed` говорит, что это:
    подтверждённое человеком или пока догадка позиционного сопоставления.
    """
    recorded = slot.lesson
    topic = recorded or suggested.get(slot.pk)

    return {
        "id": slot.pk,
        "course": {"id": slot.course_id, "name": slot.course.name},
        "lesson_number": slot.lesson_number,
        "is_cancelled": slot.is_cancelled,
        "is_extra": slot.is_extra,
        "reason": slot.reason,
        "confirmed": recorded is not None,
        "topic": (
            None
            if topic is None
            else {
                "id": topic.pk,
                # тема, в которой лежит урок: «дописать строку сюда» кладёт
                # новую на тот же уровень, а дерева плана на этом экране нет
                "section_id": topic.parent_id,
                "title": topic.title,
                "objectives": topic.objectives,
                "body": topic.body,
                "formative": topic.formative,
                "homework": topic.homework,
            }
        ),
        "works": [
            {
                "id": work.pk,
                "title": work.title,
                "state": work.state(),
                "on_paper": work.on_paper,
                # чем домашняя отличается от классной: только тем, в каком
                # разделе урока её показать. Пустая домашняя и пустая
                # классная в данных иначе неразличимы
                "is_homework": work.is_homework,
            }
            for work in slot.works.all()
        ],
    }
