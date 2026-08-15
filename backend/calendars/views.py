from config.access import SchoolScopedViewSet
from config.errors import Codes, api_error
from django.db.models import ProtectedError
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import DayException, SchoolYear, Term
from .serializers import (
    DayExceptionSerializer,
    SchoolYearSerializer,
    TermSerializer,
)


def usage_of(year) -> dict:
    """
    Что удаление года унесёт с собой и что его удержит.

    Год стоит выше всего остального: курсы висят на нём каскадом, а на
    курсах — назначения, методисты и школьное расписание. Одной кнопкой это
    сносит работу всей школы, поэтому числа считаются **до** удаления и
    показываются в подтверждении: «разметка» — это далеко не всё, что уйдёт.

    Личные уроки и строки плана держат курс через PROTECT и потому стоят
    отдельно: пока они есть, удаления не будет вовсе.

    Импорты локальные: `schedule` и `plans` уже импортируют `calendars`.
    """
    from plans.models import PlanNode
    from schedule.models import Course, CourseAssignment, Lesson
    from works.models import Work

    return {
        "courses": Course.objects.filter(year=year).count(),
        "assignments": CourseAssignment.objects.filter(course__year=year).count(),
        "terms": year.terms.count(),
        "exceptions": year.exceptions.count(),
        # то, что удержит: чужая работа внутри курсов этого года
        "slots": Lesson.objects.filter(year=year).count(),
        "plan_rows": PlanNode.objects.filter(course__year=year).count(),
        "works": Work.objects.filter(course__year=year).count(),
    }


class SchoolYearViewSet(SchoolScopedViewSet):
    """
    The school's years: CRUD, the expanded calendar and the statistics.

    Everybody in the school reads them — the calendar is shared — and only an
    administrator changes them.
    """

    serializer_class = SchoolYearSerializer
    queryset = SchoolYear.objects.prefetch_related("exceptions")

    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        """Что стоит на этом годе — для подтверждения удаления."""
        return Response(usage_of(self.get_object()))

    def perform_destroy(self, instance):
        """
        Удаление года: отказ, если внутри чужая работа.

        Проверка стоит **до** `delete()`, а не в обработчике исключения,
        ради сообщения: `ProtectedError` знает только про `Course.year` —
        первую связь на пути, — а сказать надо про уроки и план, из-за
        которых курс и не удаляется. Обработчик всё равно оставлен: между
        проверкой и удалением коллега может завести первый урок.
        """
        used = usage_of(instance)

        def refuse():
            api_error(
                Codes.YEAR_IN_USE,
                f"«{instance.name}» is in use: {used['slots']} lessons, "
                f"{used['plan_rows']} plan rows and {used['works']} works "
                "belong to its courses. Ask their teachers to clear them first.",
                name=instance.name,
                **used,
            )

        if used["slots"] or used["plan_rows"] or used["works"]:
            refuse()

        try:
            instance.delete()
        except ProtectedError:
            refuse()

    @action(detail=True, methods=["get"])
    def days(self, request, pk=None):
        """The calendar day by day. Computed on the fly, never stored."""
        year = self.get_object()
        return Response(
            {
                "start_date": year.start_date,
                "end_date": year.end_date,
                "weekend_days": year.weekend_days,
                "days": [services.day_payload(day) for day in year.build_days()],
            }
        )

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """Study days in total and per weekday."""
        year = self.get_object()
        return Response(services.build_stats(year.build_days()))


class DayExceptionViewSet(SchoolScopedViewSet):
    """Calendar markup. The list is filtered by ?year=<id>."""

    serializer_class = DayExceptionSerializer
    queryset = DayException.objects.all()
    # the markup has no school of its own: it hangs off a year
    school_path = "year__school"

    def get_queryset(self):
        queryset = super().get_queryset()

        year = self.request.query_params.get("year")
        if year:
            # a non-numeric value must not blow up on a cast
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return queryset.select_related("year")


class TermViewSet(SchoolScopedViewSet):
    """Quarters and semesters. The list is filtered by ?year=<id>."""

    serializer_class = TermSerializer
    queryset = Term.objects.all()
    school_path = "year__school"

    def get_queryset(self):
        queryset = super().get_queryset()

        year = self.request.query_params.get("year")
        if year:
            # a non-numeric value must not blow up on a cast
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return queryset.select_related("year")
