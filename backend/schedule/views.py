from collections import defaultdict
from datetime import timedelta

from calendars import services as calendar_services
from calendars.models import SchoolYear
from config.access import (
    IsCourseTeacherOrSchoolAdmin,
    IsSchoolAdminForWrite,
    user_school_id,
    allowed_to_write_schedule,
    IsSchoolMember,
    IsFamily,
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
from plans.serializers import person

from . import history, services
from .services import sweepable
from schools import roster, services as school_services
from schools.models import School

from .models import (
    BellTime,
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
from .serializers import (
    AttendanceSerializer,
    BellsSerializer,
    BulkDeleteSerializer,
    CloseDaySerializer,
    CourseMethodistSerializer,
    CourseStudentSerializer,
    SubjectSerializer,
    CopySerializer,
    RepeatSerializer,
    CourseAssignmentSerializer,
    CourseSerializer,
    GradeLevelSerializer,
    HomegroupSerializer,
    HomegroupStudentSerializer,
    RoomSerializer,
    SlotMoveSerializer,
    SlotRoomSerializer,
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


class HomegroupViewSet(SchoolScopedViewSet):
    """
    Классы школы: 6А, 6Б, DP1. Ведёт их администратор, видят все.

    Курсов в ответе нет намеренно: класс курса выводится из его учеников, и
    записанной связи между ними не существует — см. `Homegroup` в моделях.

    Список сужается годом (`?year=`): в следующем году 6А становится 7А, и
    это другая строка, а не переименованная эта.
    """

    serializer_class = HomegroupSerializer
    queryset = Homegroup.objects.annotate(
        student_count=Count("students", filter=Q(students__removed_at__isnull=True))
    ).select_related("grade", "tutor")

    def get_queryset(self):
        queryset = super().get_queryset()
        year = self.request.query_params.get("year")
        if year:
            queryset = (
                queryset.filter(year_id=year) if year.isdigit() else queryset.none()
            )
        return queryset

    def perform_destroy(self, instance):
        """
        Класс, в котором кто-то числится, не удаляется молча.

        Удаление унесло бы с собой строки принадлежности — то есть ответ на
        вопрос «кто где учился в сентябре», по которому собиралось всё
        расписание. Сначала выведите людей.
        """
        inside = instance.students.filter(removed_at__isnull=True).count()
        if inside:
            api_error(
                Codes.HOMEGROUP_IN_USE,
                f"«{instance.name}» still holds {inside} students: "
                "move them out first.",
                name=instance.name,
                students=inside,
            )
        instance.delete()


class HomegroupStudentViewSet(SchoolScopedViewSet):
    """
    Кто в классе: строка «класс и ученик», ставит её администратор.

    Та же форма, что у зачисления на курс (`CourseStudentViewSet`), и то же
    правило: строка не удаляется, а снимается. `DELETE` поэтому ставит
    `removed_at`, а не убирает запись.
    """

    serializer_class = HomegroupStudentSerializer
    queryset = HomegroupStudent.objects.select_related("student", "homegroup")
    school_path = "homegroup__school"

    def get_queryset(self):
        queryset = super().get_queryset()
        group = self.request.query_params.get("homegroup")
        if group:
            queryset = (
                queryset.filter(homegroup_id=group)
                if group.isdigit()
                else queryset.none()
            )
        # снятые не показываются по умолчанию: экран отвечает на «кто сейчас
        # в классе», а история нужна редко и спрашивается явно
        if self.request.query_params.get("all") != "1":
            queryset = queryset.filter(removed_at__isnull=True)
        return queryset

    def perform_destroy(self, instance):
        """Снятие, а не удаление: где человек учился, остаётся правдой."""
        instance.removed_at = timezone.now()
        instance.save(update_fields=["removed_at"])


class RoomViewSet(SchoolScopedViewSet):
    """
    Кабинеты школы: список ведёт администратор, выбирают из него все.

    Устроен как предметы рядом и по тем же доводам: читает вся школа —
    учитель выбирает кабинет, ставя себе час, — правит администратор.

    Архивные из ответа не убираются: страница справочника показывает их
    отдельно, а выбор в расписании сужает сам. Убери их здесь — и
    администратор не смог бы вернуть кабинет из архива, не зная его id.
    """

    serializer_class = RoomSerializer
    # порядок назван вслух: группировка от `annotate` стирает `ordering` из
    # `Meta`, и список приезжал как попало — та же ловушка, что была у курсов
    # в `layout_agenda`. Снаружи это выходит не поломкой, а тестом, который
    # проходит через раз: «214, Спортзал» и «Спортзал, 214» одинаково законны
    # для базы, и какой из них случится, решает план запроса
    queryset = Room.objects.annotate(slot_count=Count("slots")).order_by(
        *Room._meta.ordering
    )

    def perform_destroy(self, instance):
        """
        Кабинет, в котором уже шли уроки, не удаляется: `PROTECT` говорит так.

        И это не формальность: «урок шёл в 214» — факт прошедшего дня, и
        оттого, что кабинет отдали под склад, он не перестаёт быть правдой.
        Для склада есть архив, о нём и говорит отказ.
        """
        try:
            instance.delete()
        except ProtectedError:
            api_error(
                Codes.ROOM_IN_USE,
                f"«{instance.name}» is used by {instance.slots.count()} lessons: "
                "archive it instead of deleting.",
                name=instance.name,
                slots=instance.slots.count(),
            )


class BellsView(APIView):
    """
    Школьный день: сколько в нём уроков и во сколько каждый из них идёт.

    Читают все, правит администратор — как предметы и параллели рядом.

    **Правится целиком**, одним PUT, а не по строке: тот же приём, что у шкалы
    работы и строк шаблона, и по той же причине — это одна вещь, а не десять
    независимых. Построчный CRUD потребовал бы своей нумерации ради формы, у
    которой её нет: номер урока и есть ключ.

    Длина дня едет здесь же, а не своим адресом рядом: «убрать седьмой урок» и
    «стереть время седьмого урока» — одно движение человека, и разными
    запросами оно оставляло бы школу в состоянии, которого она не просила.

    Пустой список звонков законен и означает «звонков нет»: до них школа жила,
    и сетка покажет номера, как показывала.

    Ответ несёт ещё и `busiest` — самый поздний номер, на котором в школе
    стоит занятие. Сокращение дня уже расставленные часы не отменяет (иначе
    школа с восьмиурочным прошлым не перешла бы на шесть уроков никогда),
    поэтому число это не запрет, а то, что показывают рядом с кнопкой: видно
    заранее, что снимаемый номер не пустой.
    """

    # `IsTeacher` рядом с админской проверкой, а не вместо: раздел стоит под
    # `/api/school/`, то есть в учительской половине, и ученику он не
    # предназначен. Ученический интерфейс сетки недели не показывает вовсе —
    # понадобится, звонки поедут в его собственный адрес, а не сюда.
    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get(self, request):
        return Response(self._payload(user_school_id(request.user)))

    def put(self, request):
        school_id = user_school_id(request.user)
        form = BellsSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        services.set_school_day(
            school_id,
            form.validated_data["lessons_per_day"],
            form.validated_data["bells"],
        )
        return Response(self._payload(school_id))

    @staticmethod
    def _payload(school_id) -> dict:
        return {
            "lessons_per_day": School.objects.values_list(
                "lessons_per_day", flat=True
            ).get(pk=school_id),
            "busiest": services.busiest_lesson_number(school_id),
            "bells": [
                {
                    "number": bell.number,
                    "starts_at": bell.starts_at.strftime("%H:%M"),
                    "ends_at": bell.ends_at.strftime("%H:%M"),
                }
                for bell in BellTime.objects.filter(school_id=school_id)
            ],
        }


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

    # Родителю то же самое, но про его ребёнка: экран отвечает на вопрос
    # «как дела в курсах», и вопрос этот у родителя тот же самый. Чей
    # именно экран, решает одно место на всё приложение.
    permission_classes = [IsAuthenticated, IsSchoolMember, IsFamily]

    def get(self, request):
        from families.viewing import subject_of

        student = subject_of(request)
        rows = (
            # только курсы своей школы: строки прошлой школы остаются в базе
            # — они след того, что человек там учился, — но в его списке им
            # места нет
            CourseStudent.objects.filter(
                student=student, course__school_id=student.school_id
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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # классы курса выводятся из его учеников: считаем один раз на ответ,
        # а не по курсу на строку — на девятнадцати курсах это девятнадцать
        # лишних запросов
        context["course_homegroups"] = self.course_homegroups
        return context

    def course_homegroups(self):
        if not hasattr(self, "_course_homegroups"):
            self._course_homegroups = Slot.homegroups_by_course(
                self.request.user.school_id
            )
        return self._course_homegroups

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

    def guard_order(self, course):
        """
        Пост-условие: после правки очередь записей осталась очередью.

        Проверок «нельзя вот так» было девять штук в девяти местах, и
        каждая новая ручка их не наследовала: `close` писал связь мимо всех
        правил, отмена прятала запись, копирование в прошлое дырявило
        хвост. Поэтому правило одно и стоит **после** записи, внутри
        транзакции: сделали — спросили — откатили, если сломали. Так же
        устроен перенос занятия, и это единственный путь, который никогда
        не тёк.
        """
        broken = Slot.broken_record(course, timezone.localdate())
        if broken is None:
            return

        api_error(
            Codes.SLOT_ORDER_BROKEN,
            f"{broken.date} would sit unrecorded among closed lessons: "
            "records go one after another, without gaps.",
            field="date",
            date=str(broken.date),
        )

    def snapshot(self, course, action, detail="", batch=None):
        """
        Снять снимок расписания курса — перед тем, как его изменят.

        Зовётся из каждого пишущего пути **до** самой правки: снимок
        отвечает на вопрос «как было», а не «как стало». Полноту вызовов
        сторожит `schedule/test_history_wiring.py` — потестовый перечень тут
        не годится, новый эндпоинт в него никто не обязан дописывать.
        """
        return history.take(course, self.request.user, action, detail, batch=batch)

    def snapshot_all(self, courses, action, detail=""):
        """
        То же, но для действия, которое идёт по нескольким курсам.

        Снимки кладутся под одной партией и отменяются вместе: вернуть один
        курс из трёх значит оставить расписание в состоянии, которого не
        было никогда.
        """
        import uuid

        batch = uuid.uuid4()
        for course in courses:
            self.snapshot(course, action, detail, batch=batch)
        return batch

    def perform_create(self, serializer):
        self.require_write(serializer.validated_data["course"])
        with transaction.atomic():
            self.snapshot(serializer.validated_data["course"], "create")
            slot = serializer.save()
            # час, созданный в закрытом прошлом, — та же дыра, что и
            # незакрытый: очередь встанет на нём
            self.guard_order(slot.course)

    def perform_update(self, serializer):
        with transaction.atomic():
            self.snapshot(serializer.instance.course, "edit")
            slot = serializer.save()
            # сюда попадают и правка даты мимо `move`, и возврат отменённого
            # часа: оба способны обогнать записи или открыть дыру
            self.guard_order(slot.course)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # функцией, а не значением: запрос нужен только тем ответам, где
        # долги показывают, а контекст строится и на запись тоже
        context["recorded_courses"] = self.recorded_courses
        # то же и с занятостью кабинета, но с одной разницей: она считается
        # по **периоду**, а его знает только список. Ответу про один час
        # передавать нечего, и он спрашивает про себя сам (`shares_room`)
        if self.action == "list":
            context["room_clashes"] = self.room_clashes
            context["student_clashes"] = self.student_clashes
            context["course_homegroups"] = self.course_homegroups
        return context

    def course_homegroups(self):
        """Классы каждого курса — выведенные из учеников, одним запросом."""
        if not hasattr(self, "_course_homegroups"):
            self._course_homegroups = Slot.homegroups_by_course(
                self.request.user.school_id
            )
        return self._course_homegroups

    def student_clashes(self):
        """Кто из учеников стоит в двух местах разом — одним запросом на показ."""
        if not hasattr(self, "_student_clashes"):
            params = self.request.query_params
            start, end = read_date(params.get("start")), read_date(params.get("end"))
            self._student_clashes = (
                Slot.student_clashes(
                    school_id=self.request.user.school_id, start=start, end=end
                )
                if start and end and start <= end
                else {}
            )
        return self._student_clashes

    def room_clashes(self):
        """
        Часы, делящие неделимый кабинет, — одним запросом на весь показ.

        Границы берутся у самого запроса и тем же `read_date`, что и фильтр
        списка: два разбора одного параметра разошлись бы в первой же правке,
        и разошлись бы молча — предупреждение просто не появилось бы.
        Периода не назвали (список за весь год) — считать нечего: обходить
        год ради метки в клетке дороже, чем промолчать.
        """
        if not hasattr(self, "_room_clashes"):
            params = self.request.query_params
            start, end = read_date(params.get("start")), read_date(params.get("end"))
            self._room_clashes = (
                Slot.room_clashes(
                    school_id=self.request.user.school_id, start=start, end=end
                )
                if start and end and start <= end
                else set()
            )
        return self._room_clashes

    def recorded_courses(self):
        """Курсы школы, в которых запись уже начали, — одним запросом."""
        if not hasattr(self, "_recorded_courses"):
            self._recorded_courses = set(
                Slot.objects.filter(
                    course__school_id=self.request.user.school_id,
                    lesson__isnull=False,
                ).values_list("course_id", flat=True)
            )
        return self._recorded_courses

    def perform_destroy(self, instance):
        """
        Занятие с записью не удаляют: сначала снимают запись.

        Раньше одиночное удаление было свободным — «нажать на клетку и
        удалить её обдуманное действие», — и это было верно, пока клетка
        ничего не значила. Теперь за ней бывает записан урок, и удаление
        уносит запись молча: строка плана возвращается в общую очередь и
        получает **другую** дату, а вместе с ней уезжает и всё, что за ней.

        Массовых операций это правило касалось всегда (`sweepable`
        пропускает всё, на чём есть запись); одиночное удаление было
        единственной дырой в нём.
        """
        if instance.lesson_id:
            api_error(
                Codes.SLOT_DELETE_RECORDED,
                f"«{instance.lesson.title}» is recorded on {instance.date}: "
                "withdraw the record before deleting the lesson.",
                field="id",
                title=instance.lesson.title,
                date=str(instance.date),
            )

        self.snapshot(instance.course, "delete", detail=str(instance.date))
        instance.delete()

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
            step=data["step"],
        )

        deleted = 0
        if data["mode"] == "replace":
            # только то, куда копирование действительно кладёт: при шаге
            # «через неделю» пропущенные недели остаются как были
            covered = services.covered_dates(
                source_start=data["source_start"],
                source_end=data["source_end"],
                target_start=data["target_start"],
                target_end=data["target_end"],
                step=data["step"],
            )
            # заменяются только пустые клетки сетки. Отмена с причиной,
            # дополнительный урок, отметка «что прошли», замена и заданная
            # работа — всё это записи о том, что было, и массовая операция
            # их не трогает. Администратора правило касается тем более: он
            # раскатывает сетку на весь год и стёр бы чужую историю разом
            deleted, _ = sweepable(
                Slot.objects.filter(course=course, date__in=covered)
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
    def repeat(self, request):
        """
        Урок и его повторы — одним движением и одной транзакцией.

        Сетку строят рядами: «вторник, третий час, до конца года» — одно
        решение, а не тридцать четыре. Раньше на это был только один путь —
        нарисовать неделю и скопировать её на период, — и ради одного
        добавленного часа приходилось раскатывать всю неделю, натыкаясь на
        уже занятые места.

        Занятое место пропускается, а не отменяет всю операцию: ряд длиной
        в год почти всегда где-нибудь во что-нибудь упрётся, и «ничего не
        создано, потому что 14 октября занято» — худший из возможных
        ответов. Считается это тем же `place_copies`, что и копирование
        периода: два разных счёта одного и того же разошлись бы молча.
        """
        form = RepeatSerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        data = form.validated_data

        course = data["course"]
        self.require_write(course)
        self.snapshot(course, "repeat", detail=str(data["date"]))
        year = course.year
        number = data["lesson_number"]
        # за границы года ряд не выходит: там урока не бывает вовсе
        until = min(data["until"], year.end_date)

        study = {day.date for day in year.build_days() if day.is_study}
        dates, skipped = services.repeat_dates(
            data["date"], until, data["step"], study
        )

        with transaction.atomic():
            occupied = set(
                Slot.objects.filter(course=course, date__in=dates).values_list(
                    "date", "lesson_number"
                )
            )
            # чужой час того же учителя: двух уроков разом не бывает.
            # Учитель — ведущий этого курса, а не тот, кто нажал: сетку
            # раскатывает и администратор
            lead = (
                CourseAssignment.objects.filter(course=course)
                .values_list("teacher_id", flat=True)
                .first()
            )
            busy = {}
            if lead is not None:
                busy = {
                    (slot.date, slot.lesson_number): slot.course.name
                    for slot in Slot.objects.filter(
                        course__assignments__teacher_id=lead,
                        year=year,
                        date__in=dates,
                        is_cancelled=False,
                    )
                    .exclude(course=course)
                    .select_related("course")
                }

            result = services.place_copies(
                plan=[(day, number) for day in dates],
                skipped=skipped,
                occupied=occupied,
                busy=busy,
                # кабинет — свойство ряда целиком: «вторник, третий час, 214»
                # это одно решение, а не тридцать четыре, и проставлять его
                # потом по одному часу значило бы отменять смысл ряда
                make=lambda day, at: Slot(
                    year=year,
                    course=course,
                    date=day,
                    lesson_number=at,
                    room=data.get("room"),
                ),
            )
            Slot.objects.bulk_create(result["created"])

            # ряд, попавший в закрытое прошлое, дырявит очередь записей
            # ровно так же, как копирование
            self.guard_order(course)

        return Response(
            {
                "created": len(result["created"]),
                "skipped": result["skipped"],
                "conflicts": result["conflicts"],
            }
        )

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
            # Копирование в школьном виде идёт по всем курсам разом, поэтому
            # снимки кладутся одной партией — до первой правки, а не по ходу:
            # снятый в цикле застал бы уже изменённых соседей.
            self.snapshot_all(courses, "copy", detail=str(data["target_start"]))
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

                # копирование в уже закрытое прошлое дырявит хвост записей
                # пачкой: те же часы, что поодиночке отклоняет создание
                self.guard_order(course)

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

        **Так переносится сорванный час, и это не единственный вид
        переноса.** Расписание меняют и насовсем — «со следующей недели
        вторник третьим часом идёт в среду вторым», — и тогда ни отмены, ни
        дополнительного не было: срыва не случилось, сдвинулся сам ряд. Этот
        второй вид просит `mode=series` и уходит в `move_series` ниже.
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

        # снимок один на оба вида переноса: и разовый, и постоянный трогают
        # расписание того же курса, а `move_series` зовётся отсюда же
        self.snapshot(slot.course, "move", detail=str(slot.date))

        if target["mode"] == SlotMoveSerializer.SERIES:
            return self.move_series(slot, target)

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

            self.refuse_if_move_breaks_order(slot.course)

        return Response(arrival.data, status=status.HTTP_201_CREATED)

    def refuse_if_move_breaks_order(self, course):
        """
        Порядок записей строгий и на календарной оси тоже.

        Занятие, уехавшее за спину соседней записи, оставляет ровно ту
        дырку, которую запись напрямую сделать не даёт. Спрашивается это
        **после** переноса, внутри транзакции: отказ откатывает движение
        целиком. Оба вида переноса — разовый и рядом — спрашивают это одной
        функцией: два ответа на один вопрос разъехались бы молча.
        """
        broken = Slot.broken_record(course, timezone.localdate())
        if broken is None:
            return

        api_error(
            Codes.SLOT_MOVE_BREAKS_ORDER,
            f"The move would leave {broken.date} out of order: "
            "records go one after another, without gaps.",
            field="date",
            date=str(broken.date),
        )

    def move_series(self, slot, target):
        """
        Постоянная правка расписания: ряд переезжает, срыва не было.

        Разовый перенос выше пишет две записи — отмену здесь и
        дополнительное занятие там, — и это верно ровно тогда, когда час
        **сорвался**. Расписание же меняют и насовсем: «вторник третьим
        часом с этой недели идёт в среду вторым». Отмечать это тридцатью
        отменами и тридцатью дополнительными значит объявить тридцать
        срывов, которых не было, — а именно эти два числа администрация и
        читает.

        Поэтому здесь дата переписывается, и это тот самый случай, ради
        которого разовый перенос её переписывать отказывается. Отличает их
        вопрос «что произошло»: сорвался час — или сдвинулся ряд.

        Ряд — тот же, что у удаления ряда: **курс, день недели, номер**, от
        этого часа и до конца года. Прошлое не трогается вовсе: расписание
        меняют вперёд, а прошедшие часы — уже история.

        Три правила внутри, и все три взяты у соседей, а не выдуманы здесь:

        - **переезжает только обычный час без записи.** Отменённый,
          дополнительный и всё, на чём есть запись, остаются на месте и
          возвращаются числом `kept` — то же правило, что у `sweepable` и
          у удаления ряда;
        - **занятое место и неучебный день пропускаются, а не отменяют
          движение.** Ряд длиной в год почти всегда во что-нибудь упрётся, и
          «не переехало ничего, потому что 14 октября занято» — худший из
          возможных ответов. Так же считает `place_copies` у повтора;
        - **сам перетащенный час проверяется строго.** По нему щёлкнули, и
          молча оставить его на месте нельзя: цель занята — отказ, как у
          обычного создания.
        """
        # Постоянная правка — это смена дня недели и номера, а не сдвиг
        # всего года на девять дней. Цель в другой неделе такого смысла не
        # имеет вовсе, и угадывать за человека, что он имел в виду, дороже
        # названного отказа.
        monday = plan_services.monday_of(slot.date)
        if plan_services.monday_of(target["date"]) != monday:
            api_error(
                Codes.SLOT_MOVE_SERIES_WEEK,
                "A permanent change moves the lesson inside its own week: "
                f"pick a day of the week starting on {monday}.",
                field="date",
                start=str(plan_services.monday_of(slot.date)),
            )

        if not slot.is_regular:
            api_error(
                Codes.SLOT_MOVE_SERIES_ONE_OFF,
                "A cancelled or extra lesson is a one-off: it has no row to "
                "move. Move this lesson alone instead.",
                field="mode",
            )

        if slot.has_record():
            api_error(
                Codes.SLOT_MOVE_SERIES_RECORDED,
                "This lesson already carries a record, and a record stays on "
                "the day it happened. Move this lesson alone instead.",
                field="mode",
            )

        shift = timedelta(days=(target["date"] - slot.date).days)
        number = target["lesson_number"]
        year = slot.year
        study = {day.date for day in year.build_days() if day.is_study}

        row = [
            other
            for other in Slot.objects.filter(
                course=slot.course,
                date__gt=slot.date,
                date__lte=year.end_date,
                lesson_number=slot.lesson_number,
            ).order_by("date")
            if other.date.weekday() == slot.date.weekday()
        ]

        moved, skipped, kept = 1, 0, 0

        with transaction.atomic():
            # Первым едет сам перетащенный час, и проверяет его обычный
            # `SlotSerializer`: границы года, занятость номера у ведущего,
            # уникальность. Правила переноса не должны быть мягче правил
            # создания — здесь ровно тот же довод, что у разового.
            arrival = SlotSerializer(
                slot,
                data={
                    "date": target["date"].isoformat(),
                    "lesson_number": number,
                },
                partial=True,
                context=self.get_serializer_context(),
            )
            arrival.is_valid(raise_exception=True)
            arrival.save()

            for other in row:
                if not other.is_regular or other.has_record():
                    kept += 1
                    continue

                landing = other.date + shift
                if landing not in study or self.place_taken(other, landing, number):
                    skipped += 1
                    continue

                other.date = landing
                other.lesson_number = number
                other.save(update_fields=["date", "lesson_number"])
                moved += 1

            self.refuse_if_move_breaks_order(slot.course)

        return Response({"moved": moved, "skipped": skipped, "kept": kept})

    @action(detail=True, methods=["post"])
    def room(self, request, pk=None):
        """
        Поставить занятие в кабинет — этот час или весь его ряд.

        Расписание строят рядами, и кабинет — свойство ряда ровно в той же
        мере, что день недели и номер: «алгебра по вторникам третьим часом
        идёт в 214» — одно решение, а не тридцать четыре. Проставленный по
        клетке, он повторяет руками то, что человек уже сказал один раз, и
        первая же пропущенная клетка выглядит потом как ошибка расписания,
        а не как забытое нажатие.

        Ряд здесь **тот же**, что у переноса и у удаления ряда: курс, день
        недели, номер, от этого часа и до конца года. Третьего определения
        ряда в проекте быть не должно — они разошлись бы молча, и первым
        это заметил бы человек, у которого «весь ряд» означал разное в
        соседних пунктах одного меню.

        Два правила, и оба взяты у соседей:

        - **час, по которому щёлкнули, получает кабинет всегда.** По нему
          нажали, и это ровно то, что делает одиночная правка сегодня:
          отменённому и записанному кабинет проставить можно, потому что
          «где стоял час» — не запись о том, что в нём произошло;
        - **остальные часы ряда — только обычные и без записи.** «Урок шёл
          в 214» — факт прошедшего дня, и переписывать его задним числом
          нельзя; у дополнительного часа ряда нет по определению. Оба
          возвращаются числом `kept` — то же правило, что у `sweepable`, у
          удаления ряда и у постоянного переноса.

        Отчёт числами, а не перерисованной сеткой: сколько часов ряда
        окажется записанными, знает только сервер, и обещать это заранее
        было бы четвёртым зеркалом его расчёта.
        """
        slot = self.get_object()
        form = SlotRoomSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        form.is_valid(raise_exception=True)
        room = form.validated_data["room"]

        self.snapshot(slot.course, "room", detail=str(slot.date))
        slot.room = room
        slot.save(update_fields=["room"])

        if form.validated_data["mode"] != SlotRoomSerializer.SERIES:
            return Response(SlotSerializer(slot, context=self.get_serializer_context()).data)

        updated, kept = 1, 0
        row = [
            other
            for other in Slot.objects.filter(
                course=slot.course,
                date__gt=slot.date,
                date__lte=slot.year.end_date,
                lesson_number=slot.lesson_number,
            ).order_by("date")
            if other.date.weekday() == slot.date.weekday()
        ]

        with transaction.atomic():
            for other in row:
                if not other.is_regular or other.has_record():
                    kept += 1
                    continue
                other.room = room
                other.save(update_fields=["room"])
                updated += 1

        return Response({"updated": updated, "kept": kept})

    def place_taken(self, slot, date, number) -> bool:
        """
        Занято ли место, куда едет час ряда.

        Спрашивается дважды и о разном: у **курса** место занимает любой его
        час, включая отменённый, — там стоит ключ уникальности; у
        **ведущего** — только живой, потому что отменённый час его время
        освобождает. Пока вопрос был один, ряд утыкался в собственную же
        отмену и пропускал неделю без причины.
        """
        mine = (
            Slot.objects.filter(course=slot.course, date=date, lesson_number=number)
            .exclude(pk=slot.pk)
            .exists()
        )
        if mine:
            return True

        lead = (
            CourseAssignment.objects.filter(course=slot.course)
            .values_list("teacher_id", flat=True)
            .first()
        )
        return (
            Slot.find_conflict(
                teacher_id=lead,
                year=slot.year,
                date=date,
                lesson_number=number,
                exclude_pk=slot.pk,
            )
            is not None
        )

    @action(detail=False, methods=["delete"])
    def bulk(self, request):
        """
        Убрать уроки курса за период. Правит тот, кому курс дозволен.

        Сужается это до **ряда** — день недели и номер, — и тем же
        эндпоинтом: ряд и есть период с двумя условиями. Сетку строят
        рядами, разбирают её так же, и второго пути удаления заводить
        незачем — два счёта уходящего разошлись бы молча.
        """
        params = request.query_params
        form = BulkDeleteSerializer(
            data={
                "course": params.get("course"),
                "start": params.get("start"),
                "end": params.get("end"),
                "only_regular": params.get("only_regular", False),
                "weekday": params.get("weekday") or None,
                "lesson_number": params.get("lesson_number") or None,
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
        if data.get("weekday") is not None:
            # `date.weekday()` в Postgres — это `ISO` минус единица; фильтр
            # берёт готовое поле, чтобы не тащить даты в питон
            queryset = queryset.filter(date__iso_week_day=data["weekday"] + 1)
        if data.get("lesson_number") is not None:
            queryset = queryset.filter(lesson_number=data["lesson_number"])

        kept = 0
        if data["only_regular"]:
            # всё, что человек отметил руками, переживает массовую чистку
            total = queryset.count()
            queryset = sweepable(queryset)
            kept = total - queryset.count()

        # Уборка бывает и по одному курсу, и по всем сразу, поэтому курсы
        # берутся у самой выборки: снимок нужен ровно тем, кого она тронет.
        # Считается это **до** удаления — после спрашивать было бы не у кого
        self.snapshot_all(
            list(Course.objects.filter(pk__in=queryset.values("course"))),
            "sweep",
            detail=str(data["start"]),
        )
        deleted, _ = queryset.delete()
        # сколько уцелело — не мелочь: ряд, из которого убрали половину,
        # иначе выглядит как неудавшееся удаление
        return Response({"deleted": deleted, "kept": kept})

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
            .select_related("course", "room")
        )

        # кабинеты, делимые с чужим часом: одним запросом на весь период —
        # по той же причине, что и список «начавших запись» ниже. Считается
        # это по **школе**, а не по своим курсам: в кабинет к учителю встаёт
        # чужой класс, и не сказать ему об этом значит не сказать никому
        clashes = Slot.room_clashes(
            school_id=request.user.school_id, start=start, end=end
        )

        # долг — прошедший час без записи, и только в курсе, где запись уже
        # начали: тому, кто кнопкой не пользуется, каждый прошедший час был
        # бы долгом. Список «начавших» берётся одним запросом на всю сетку,
        # а не по курсу на каждую клетку
        today = timezone.localdate()
        started = set(
            Slot.objects.filter(
                course__in=self.my_courses(), lesson__isnull=False
            ).values_list("course_id", flat=True)
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
                    "recorded": slot.lesson_id is not None,
                    "room_id": slot.room_id,
                    "room_name": slot.room.name if slot.room_id else None,
                    "room_clash": slot.id in clashes,
                    "debt": (
                        slot.lesson_id is None
                        and not slot.is_cancelled
                        and slot.date <= today
                        and slot.course_id in started
                    ),
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
            # Закрывают долги пачкой и обычно по одному курсу, но список
            # присылает клиент, и курсов в нём может оказаться несколько —
            # снимок берётся у каждого, одной партией и до первой записи
            self.snapshot_all(
                {slot.course for slot in mine.values()}, "close", detail=str(len(rows))
            )
            for row in rows:
                slot = mine.get(row["slot"])
                if slot is None:
                    api_error(
                        Codes.SLOT_NOT_MINE,
                        "That lesson belongs to a course you do not teach.",
                        field="closed",
                    )

                # Через тот же сериализатор, что и одиночная запись, а не
                # полем напрямую. Полем — это был второй способ записывать,
                # не знающий ни про очередь, ни про подсказанную строку, ни
                # про «только прошедшее»: закрыть можно было будущий час
                # чужой строкой и не по порядку.
                changes = (
                    {"is_cancelled": True, "reason": row.get("reason", "")}
                    if row.get("cancelled")
                    else {"lesson": row.get("lesson").pk if row.get("lesson") else None}
                )
                form = SlotSerializer(
                    slot,
                    data=changes,
                    partial=True,
                    context=self.get_serializer_context(),
                )
                form.is_valid(raise_exception=True)
                form.save()

            # порядок строк в запросе задаёт клиент, и закрыть вторую,
            # оставив первую, он всё ещё может — это ловит общая проверка
            for course in {slot.course for slot in mine.values()}:
                self.guard_order(course)

        return Response({"closed": len(rows)})

    def undo_scope(self):
        """
        Чьи шаги человек вправе видеть и отменять.

        У администратора это вся школа — он и правит всю школу; у учителя
        его курсы. Тот же ответ, что даёт `require_write`, только выборкой:
        спрашивать право по одному курсу в цикле значило бы завести второе
        определение того же.
        """
        if self.request.user.is_school_admin:
            return Course.objects.filter(school_id=self.request.user.school_id)
        return self.my_courses()

    def undo_course(self, write=False):
        """
        Курс, про расписание которого спрашивают, — из `?course=`.

        **Без `?course=` вопрос другой**, и это не небрежность вызывающего.
        Учебный план всегда открыт на одном курсе, а расписание — нет: на
        «Моём расписании» за пять минут правят три курса подряд, и «отменить
        последнее» там значит последнее вообще. Тогда курс не спрашивается, а
        **находится** — по самому свежему снимку среди дозволенных.

        Чужой курс тут неотличим от несуществующего, как везде.
        """
        asked = self.request.query_params.get("course")

        if asked:
            course = get_object_or_404(self.undo_scope(), pk=asked)
        else:
            step = (
                history.SlotSnapshot.objects.filter(course__in=self.undo_scope())
                .order_by("-made_at", "-id")
                .select_related("course")
                .first()
            )
            if step is None:
                return None
            course = step.course

        if write:
            self.require_write(course)
        return course

    @action(detail=False, methods=["get"], url_path="history", url_name="history")
    def slot_history(self, request):
        """
        Чем можно отменить — снимки расписания курса, свежие первыми.

        Отдаётся и то, что нужно кнопке: какое действие последовало за
        снимком и чего оно коснулось. Безымянная отмена страшнее, чем
        полезна: по ней не поймёшь, вернёшь ты удалённый час или чужую
        правку получасовой давности.
        """
        course = self.undo_course()
        rows = (
            history.SlotSnapshot.objects.filter(course=course)
            .select_related("made_by")
            .order_by("-made_at", "-id")
            if course is not None
            else history.SlotSnapshot.objects.none()
        )

        return Response(
            {
                "steps": [
                    {
                        "id": item.pk,
                        "action": item.action,
                        "detail": item.detail,
                        "made_at": item.made_at,
                        "by_lead": item.by_lead,
                        "who": person(item.made_by),
                        "mine": item.made_by_id == request.user.pk,
                    }
                    for item in rows
                ]
            }
        )

    @action(detail=False, methods=["post"], url_path="undo", url_name="undo")
    def slot_undo(self, request):
        """
        Вернуть расписание курса к состоянию перед последним действием.

        **Шаг ровно один, и номер снимка ручка не принимает.** У плана
        принимает — там отменяют и чужую правку недельной давности, — а тут
        глубже одного шага не ходят: расписание правят и отменяют в одну
        минуту. Путь, которым интерфейс не пользуется, всё равно никто не
        проверяет, а через него как раз и проходит самое опасное:
        восстановление поверх работы, сделанной после снимка.

        **Отменяется партия целиком, а не один курс.** Копирование в
        школьном виде и массовая уборка идут по нескольким курсам сразу;
        вернуть тот, из которого спросили, и оставить соседей значит
        собрать расписание, которого не было никогда.

        Восстановление проходит ту же проверку очереди, что и любая правка:
        если за это время час записали, вернуть клетку на место иногда уже
        нельзя. Отказ приходит обычным кодом и отменяет всё целиком.
        """
        course = self.undo_course(write=True)

        step = (
            history.SlotSnapshot.objects.filter(course=course)
            .order_by("-made_at", "-id")
            .first()
            if course is not None
            else None
        )
        if step is None:
            api_error(
                Codes.SLOT_NOTHING_TO_UNDO,
                "There is nothing to undo: no snapshot of this schedule was kept.",
                field="snapshot",
            )

        with transaction.atomic():
            # сам откат — тоже изменение расписания, и его тоже надо уметь
            # отменить: иначе «вернул не то» становится тупиком. Снимок
            # берётся по всем курсам партии, а не по одному спрошенному
            touched = list(
                Course.objects.filter(
                    pk__in=history.SlotSnapshot.objects.filter(
                        batch=step.batch
                    ).values("course")
                )
            )
            self.snapshot_all(touched, "undo", step.detail)
            result = history.restore_batch(step.batch)
            # Снимок мог не пережить собственную уборку: `take` зовёт
            # `prune`, а тот держит последние двадцать. Восстановить нечего —
            # это отказ, а не тихий успех: молчаливый ноль читается как
            # «отменил», и человек уходит с неотменённым расписанием
            if not result["courses"]:
                api_error(
                    Codes.SLOT_NOTHING_TO_UNDO,
                    "That snapshot is gone: only the last steps are kept.",
                    field="snapshot",
                )
            for one in touched:
                self.guard_order(one)

        return Response(result)

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
                # чем домашняя отличается от классной: только тем, в каком
                # разделе урока её показать. Пустая домашняя и пустая
                # классная в данных иначе неразличимы
                "is_homework": work.is_homework,
            }
            for work in slot.works.all()
        ],
    }
