from collections import defaultdict

from calendars import services as calendar_services
from calendars.models import SchoolYear
from config.access import IsSchoolMember, SchoolScopedViewSet, TeacherScopedViewSet
from config.errors import Codes, api_denied, api_error
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.db.models import ProtectedError
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from plans.models import PlanNode

from . import importing, services
from .models import Course, CourseAssignment, GradeLevel, LessonSlot, MasterSlot, Subject
from .serializers import (
    BulkDeleteSerializer,
    SubjectSerializer,
    CopySerializer,
    CourseAssignmentSerializer,
    CourseSerializer,
    GradeLevelSerializer,
    ImportFromSchoolSerializer,
    LessonSlotSerializer,
    MasterSlotSerializer,
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
    queryset = Subject.objects.all()

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
    queryset = GradeLevel.objects.all()

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
            GradeLevel(school=school, level=level, name=f"Grade {level}")
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
        Taking a course away from somebody. The work stays where it is.

        Three answers were possible and only one of them is honest. Deleting
        the lessons and the plan along with the assignment would destroy a
        colleague's year from an administrator's screen — never. Refusing
        while anything exists would deadlock the moment a teacher leaves the
        school. So: the assignment goes, everything written under it stays,
        and the first attempt is refused with the counts so that nobody does
        it by accident. `?force=true` is the confirmation.

        Nothing is hidden afterwards either: `Course.objects.for_teacher`
        keeps a course visible to whoever already has work in it.
        """
        slots = LessonSlot.objects.filter(
            course=instance.course, teacher=instance.teacher
        ).count()
        rows = PlanNode.objects.filter(
            course=instance.course, teacher=instance.teacher
        ).count()
        master = MasterSlot.objects.filter(
            course=instance.course, teacher=instance.teacher
        ).count()

        forced = self.request.query_params.get("force", "").lower() == "true"
        if (slots or rows or master) and not forced:
            api_error(
                Codes.ASSIGNMENT_IN_USE,
                f"{full_name(instance.teacher)} has {slots} lessons, {rows} plan "
                f"rows and {master} timetable rows in «{instance.course.name}». "
                "Unassigning keeps all of it; repeat with force=true to confirm.",
                teacher=full_name(instance.teacher),
                course=instance.course.name,
                slots=slots,
                plan_rows=rows,
                master_slots=master,
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

        return queryset.select_related("year", "subject", "grade").prefetch_related(
            "assignments__teacher"
        )

    def perform_destroy(self, instance):
        """
        Deleting a course that somebody teaches is refused, not cascaded.

        The slots and the plan rows hold it under PROTECT — an administrator
        must not wipe a colleague's year with one button. The answer says how
        many lessons and plan rows are in the way and whose they are.
        """
        try:
            instance.delete()
        except ProtectedError:
            slots = instance.slots.count()
            rows = instance.plan_nodes.count()
            teachers = sorted(
                {
                    str(name or email)
                    for name, email in instance.slots.values_list(
                        "teacher__first_name", "teacher__email"
                    ).union(
                        instance.plan_nodes.values_list(
                            "teacher__first_name", "teacher__email"
                        )
                    )
                }
            )
            api_error(
                Codes.COURSE_IN_USE,
                f"«{instance.name}» is in use: {slots} lessons and {rows} plan "
                f"rows belong to {', '.join(teachers)}. Ask them to clear it first.",
                name=instance.name,
                slots=slots,
                plan_rows=rows,
                teachers=teachers,
            )


class LessonSlotViewSet(TeacherScopedViewSet):
    """
    Lesson slots — personal to the teacher inside a shared course.

    The list is filtered by `course`, `start` and `end`; beyond CRUD there are
    the bulk operations: copy, bulk and stats.
    """

    serializer_class = LessonSlotSerializer
    queryset = LessonSlot.objects.all()

    def own_slots(self):
        return LessonSlot.objects.filter(teacher=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset().select_related("course", "year")
        # year.periods() нужен каждому слоту для предупреждения о неучебном дне
        queryset = queryset.prefetch_related("year__exceptions")

        params = self.request.query_params
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
        Copying one course. Called inside a transaction, because the lessons
        created for the previous course occupy numbers for the next one.
        """
        target = (data["target_start"], data["target_end"])
        year = course.year
        teacher = self.request.user

        source_numbers = defaultdict(list)
        source_slots = self.own_slots().filter(
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
            # only regular lessons are replaced: a cancellation or an extra
            # lesson is hand-made markup and a bulk operation must not touch it
            deleted, _ = self.own_slots().filter(
                course=course,
                date__range=target,
                is_extra=False,
                is_cancelled=False,
            ).delete()

        occupied = set(
            self.own_slots()
            .filter(course=course, date__range=target)
            .values_list("date", "lesson_number")
        )

        # numbers this teacher already spends on their other courses: nobody
        # runs two lessons at once, so such slots are skipped with a report
        busy = {
            (slot.date, slot.lesson_number): slot.course.name
            for slot in self.own_slots()
            .filter(year=year, date__range=target, is_cancelled=False)
            .exclude(course=course)
            .select_related("course")
        }

        result = services.place_copies(
            plan=plan,
            skipped=skipped,
            occupied=occupied,
            busy=busy,
            make=lambda day, number: LessonSlot(
                year=year,
                teacher=teacher,
                course=course,
                date=day,
                lesson_number=number,
            ),
        )
        LessonSlot.objects.bulk_create(result["created"])

        return {
            "created": len(result["created"]),
            "skipped": result["skipped"],
            "deleted": deleted,
            "conflicts": result["conflicts"],
        }

    @action(detail=False, methods=["post"])
    def copy(self, request):
        """
        Repeat the layout of a source period onto a target period.

        Without `course_id` the whole schedule travels: every course this
        teacher actually has lessons in, whose year touches the target.
        Cancelled and extra lessons are copied in neither mode.
        """
        form = CopySerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        data = form.validated_data

        one = data.get("course")
        if one is not None:
            courses = [one]
        else:
            # only the courses this teacher works in: the school may hold
            # dozens, and the others have nothing of theirs to copy
            courses = list(
                Course.objects.for_teacher(request.user)
                .filter(
                    year__start_date__lte=data["target_end"],
                    year__end_date__gte=data["target_start"],
                )
                .select_related("year")
            )

        totals = {"created": 0, "skipped": 0, "deleted": 0, "conflicts": []}
        study_by_year = {}

        with transaction.atomic():
            for course in courses:
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

    @action(detail=False, methods=["delete"])
    def bulk(self, request):
        """Remove this teacher's lessons in a course over a period."""
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

        queryset = self.own_slots().filter(
            course=data["course"],
            date__range=(data["start"], data["end"]),
        )
        if data["only_regular"]:
            # hand-made markup survives a bulk clean
            queryset = queryset.filter(is_extra=False, is_cancelled=False)

        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        """
        This teacher's whole schedule for a period, every course at once.

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

        # the markup comes from the calendar: the year knows the breaks
        days = {
            day.isoformat(): {"status": "outside", "title": "", "is_study": False}
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
                    days[day.date.isoformat()] = {
                        "status": day.status,
                        "title": day.title,
                        "is_study": day.is_study,
                    }

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


class MasterSlotViewSet(SchoolScopedViewSet):
    """
    The school-wide timetable: who teaches what, and when.

    Everybody in the school reads it — a teacher needs to see what they are
    down for before importing — and only an administrator writes.

    Copying a period and clearing one work exactly as they do for a personal
    schedule, through the same `place_copies`: an administrator who has
    learnt one of the two screens has learnt both.
    """

    serializer_class = MasterSlotSerializer
    queryset = MasterSlot.objects.select_related("course", "teacher", "year")

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        for param, lookup in (
            ("year", "year_id"),
            ("teacher", "teacher_id"),
            ("course", "course_id"),
        ):
            raw = params.get(param)
            if not raw:
                continue
            queryset = (
                queryset.filter(**{lookup: raw}) if raw.isdigit() else queryset.none()
            )

        for param, lookup in (("start", "date__gte"), ("end", "date__lte")):
            raw = params.get(param)
            if not raw:
                continue
            parsed = read_date(raw)
            queryset = queryset.filter(**{lookup: parsed}) if parsed else queryset.none()

        return queryset

    def school_slots(self):
        return MasterSlot.objects.filter(school_id=self.request.user.school_id)

    def copy_one_course(self, course, data, study_dates):
        """One course of the timetable. Inside the caller's transaction."""
        target = (data["target_start"], data["target_end"])
        year = course.year

        source_numbers = defaultdict(list)
        for slot in self.school_slots().filter(
            course=course, date__range=(data["source_start"], data["source_end"])
        ):
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
            deleted, _ = self.school_slots().filter(
                course=course, date__range=target
            ).delete()

        occupied = set(
            self.school_slots()
            .filter(course=course, date__range=target)
            .values_list("date", "lesson_number")
        )

        # the teacher of this course cannot be in two rooms at once, so their
        # other courses block the hour and say so
        teacher_id = (
            self.school_slots()
            .filter(course=course)
            .exclude(teacher__isnull=True)
            .values_list("teacher_id", flat=True)
            .first()
        )
        busy = {}
        if teacher_id is not None:
            busy = {
                (slot.date, slot.lesson_number): slot.course.name
                for slot in self.school_slots()
                .filter(teacher_id=teacher_id, date__range=target)
                .exclude(course=course)
                .select_related("course")
            }

        # bulk_create writes past clean(), so the assignment is checked here
        # instead: copying a week must not be a way to hand somebody a course
        # they were taken off
        if teacher_id is not None and not CourseAssignment.objects.filter(
            course=course, teacher_id=teacher_id
        ).exists():
            api_error(
                Codes.NOT_ASSIGNED,
                f"The teacher of «{course.name}» is no longer assigned to it. "
                "Assign them again, or clear those rows first.",
                course=course.name,
            )

        result = services.place_copies(
            plan=plan,
            skipped=skipped,
            occupied=occupied,
            busy=busy,
            make=lambda day, number: MasterSlot(
                school_id=self.request.user.school_id,
                year=year,
                course=course,
                teacher_id=teacher_id,
                date=day,
                lesson_number=number,
            ),
        )
        MasterSlot.objects.bulk_create(result["created"])

        return {
            "created": len(result["created"]),
            "skipped": result["skipped"],
            "deleted": deleted,
            "conflicts": result["conflicts"],
        }

    @action(detail=False, methods=["post"])
    def copy(self, request):
        """Repeat a period of the timetable onto another period."""
        form = CopySerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        data = form.validated_data

        one = data.get("course")
        if one is not None:
            courses = [one]
        else:
            courses = list(
                Course.objects.filter(
                    pk__in=self.school_slots().values("course_id"),
                    year__start_date__lte=data["target_end"],
                    year__end_date__gte=data["target_start"],
                ).select_related("year")
            )

        totals = {"created": 0, "skipped": 0, "deleted": 0, "conflicts": []}
        study_by_year = {}

        with transaction.atomic():
            for course in courses:
                year = course.year
                if year.pk not in study_by_year:
                    study_by_year[year.pk] = {
                        day.date for day in year.build_days() if day.is_study
                    }

                result = self.copy_one_course(course, data, study_by_year[year.pk])
                for key in ("created", "skipped", "deleted"):
                    totals[key] += result[key]
                totals["conflicts"].extend(result["conflicts"])

        return Response(totals)

    @action(detail=False, methods=["delete"])
    def bulk(self, request):
        """Clear a period of the timetable, optionally for one course."""
        params = request.query_params
        start, end = (read_date(params.get(name)) for name in ("start", "end"))
        if start is None or end is None:
            api_error(
                Codes.PERIOD_REQUIRED,
                "Both «start» and «end» query parameters are required.",
                field="start",
            )
        if end < start:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )

        queryset = self.school_slots().filter(date__range=(start, end))

        course = params.get("course")
        if course:
            queryset = (
                queryset.filter(course_id=course) if course.isdigit() else queryset.none()
            )

        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """How much is laid out, and how much of it has nobody yet."""
        queryset = self.get_queryset()
        total = queryset.count()

        return Response(
            {
                "total": total,
                "unassigned": queryset.filter(teacher__isnull=True).count(),
                "teachers": queryset.exclude(teacher__isnull=True)
                .values("teacher_id")
                .distinct()
                .count(),
            }
        )


class ImportFromSchoolView(APIView):
    """
    Copy my rows of the school timetable into my own schedule.

    Any teacher of the school may do it for themselves; nobody can do it for
    anybody else, because the rows are selected by `teacher == request.user`
    and the lessons are created with the same user.

    It happens once. Afterwards the copies are ordinary lessons and the
    timetable has no hold on them.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def post(self, request):
        form = ImportFromSchoolSerializer(
            data=request.data, context={"request": request}
        )
        form.is_valid(raise_exception=True)
        data = form.validated_data

        result = importing.run_import(
            teacher=request.user,
            year=data["year"],
            courses=data.get("courses") or None,
            start=data["start"],
            end=data["end"],
            mode=data["mode"],
        )
        return Response(result)


class ImportPreviewView(APIView):
    """
    What an import would bring, before anybody presses anything.

    Same planning code as the import, so the numbers shown are the numbers
    that will happen — computed in merge mode, the cautious one: replace can
    only turn conflicts into replacements, never add new ones.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request):
        params = request.query_params
        year = SchoolYear.objects.filter(
            school_id=request.user.school_id, pk=params.get("year", 0) or 0
        ).first()
        if year is None:
            api_error(
                Codes.YEAR_REQUIRED,
                "The «year» query parameter with a school year id is required.",
                field="year",
            )

        start = read_date(params.get("start")) or year.start_date
        end = read_date(params.get("end")) or year.end_date

        plan = importing.plan_import(
            teacher=request.user, year=year, start=start, end=end
        )

        return Response(
            {
                "start": start,
                "end": end,
                "available": sum(item["available"] for item in plan["courses"]),
                "created": len(plan["slots"]),
                "skipped": plan["skipped"],
                "courses": plan["courses"],
                "conflicts": plan["conflicts"],
            }
        )
