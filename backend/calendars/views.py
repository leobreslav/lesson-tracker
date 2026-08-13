from config.access import SchoolScopedViewSet
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import DayException, SchoolYear, Term
from .serializers import (
    DayExceptionSerializer,
    SchoolYearSerializer,
    TermSerializer,
)


class SchoolYearViewSet(SchoolScopedViewSet):
    """
    The school's years: CRUD, the expanded calendar and the statistics.

    Everybody in the school reads them — the calendar is shared — and only an
    administrator changes them.
    """

    serializer_class = SchoolYearSerializer
    queryset = SchoolYear.objects.prefetch_related("exceptions")

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
