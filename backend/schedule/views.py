from collections import defaultdict

from calendars import services as calendar_services
from calendars.models import SchoolYear
from config.access import SchoolScopedViewSet, TeacherScopedViewSet
from config.errors import Codes, api_error
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.db.models import ProtectedError
from django.utils.dateparse import parse_date
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import Course, LessonSlot
from .serializers import (
    BulkDeleteSerializer,
    CopySerializer,
    CourseSerializer,
    LessonSlotSerializer,
    PeriodSerializer,
)


def read_date(value):
    """A date from a query parameter. Garbage is None, not a 500."""
    try:
        return parse_date(value or "")
    except ValueError:
        # parse_date raises on «2026-13-45»: the shape fits, the date does not
        return None


class CourseViewSet(SchoolScopedViewSet):
    """
    The school's courses. The list is filtered by ?year=<id>.

    Every teacher reads them and picks from the list; only an administrator
    creates, renames and deletes.
    """

    serializer_class = CourseSerializer
    queryset = Course.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()

        year = self.request.query_params.get("year")
        if year:
            # a non-numeric value must not blow up on a cast
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return queryset.select_related("year")

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

        created, conflicts = [], []
        for slot_date, number in plan:
            if (slot_date, number) in occupied:
                skipped += 1
                continue

            class_name = busy.get((slot_date, number))
            if class_name is not None:
                skipped += 1
                conflicts.append(
                    {
                        "date": slot_date,
                        "lesson_number": number,
                        "class_name": class_name,
                        "message": services.occupied_message(
                            slot_date, number, class_name
                        ),
                    }
                )
                continue

            occupied.add((slot_date, number))
            created.append(
                LessonSlot(
                    year=year,
                    teacher=teacher,
                    course=course,
                    date=slot_date,
                    lesson_number=number,
                )
            )

        LessonSlot.objects.bulk_create(created)

        return {
            "created": len(created),
            "skipped": skipped,
            "deleted": deleted,
            "conflicts": conflicts,
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
                Course.objects.filter(
                    pk__in=self.own_slots().values("course_id"),
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
