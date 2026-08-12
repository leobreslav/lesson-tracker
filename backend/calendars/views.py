from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import DayException, SchoolYear
from .serializers import DayExceptionSerializer, SchoolYearSerializer


def serialize_day(day: services.Day) -> dict:
    return {
        "date": day.date,
        "weekday": day.weekday,
        "status": day.status,
        "title": day.title,
        "exception": day.exception_id,
    }


class SchoolYearViewSet(viewsets.ModelViewSet):
    """Свои учебные годы: CRUD, развёрнутый календарь и статистика."""

    serializer_class = SchoolYearSerializer

    def get_queryset(self):
        # чужие годы недоступны на любом действии, включая detail-роуты
        return SchoolYear.objects.filter(owner=self.request.user).prefetch_related(
            "exceptions"
        )

    @action(detail=True, methods=["get"])
    def days(self, request, pk=None):
        """Календарь по дням. Считается на лету, в базе не хранится."""
        year = self.get_object()
        return Response(
            {
                "start_date": year.start_date,
                "end_date": year.end_date,
                "weekend_days": year.weekend_days,
                "days": [serialize_day(day) for day in year.build_days()],
            }
        )

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """Учебных дней всего и по дням недели."""
        year = self.get_object()
        return Response(services.build_stats(year.build_days()))


class DayExceptionViewSet(viewsets.ModelViewSet):
    """Исключения календаря. Список фильтруется параметром ?year=<id>."""

    serializer_class = DayExceptionSerializer

    def get_queryset(self):
        queryset = DayException.objects.filter(year__owner=self.request.user)

        year = self.request.query_params.get("year")
        if year:
            # нечисловой параметр не должен ронять запрос ошибкой приведения
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return queryset.select_related("year")
