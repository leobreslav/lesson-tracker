from collections import defaultdict

from calendars import services as calendar_services
from calendars.models import SchoolYear
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import LessonSlot, SchoolClass
from .serializers import (
    BulkDeleteSerializer,
    CopySerializer,
    LessonSlotSerializer,
    PeriodSerializer,
    SchoolClassSerializer,
)


def read_date(value):
    """Дата из параметра запроса. Мусор — это None, а не 500."""
    try:
        return parse_date(value or "")
    except ValueError:
        # parse_date падает на «2026-13-45»: формат похож, даты не существует
        return None


class SchoolClassViewSet(viewsets.ModelViewSet):
    """Классы текущего пользователя. Список фильтруется параметром ?year=<id>."""

    serializer_class = SchoolClassSerializer

    def get_queryset(self):
        # фильтр по владельцу на уровне queryset закрывает и чтение, и правку:
        # чужой объект просто не находится
        queryset = SchoolClass.objects.filter(owner=self.request.user)

        year = self.request.query_params.get("year")
        if year:
            # нечисловой параметр не должен ронять запрос ошибкой приведения
            queryset = queryset.filter(year_id=year) if year.isdigit() else queryset.none()

        return queryset.select_related("year")


class LessonSlotViewSet(viewsets.ModelViewSet):
    """
    Уроки расписания.

    Список фильтруется параметрами `class`, `start`, `end`; сверх CRUD есть
    массовые операции: copy, bulk и stats.
    """

    serializer_class = LessonSlotSerializer

    def own_slots(self):
        return LessonSlot.objects.filter(school_class__owner=self.request.user)

    def get_queryset(self):
        queryset = self.own_slots().select_related("school_class", "year")
        # year.periods() нужен каждому слоту для предупреждения о неучебном дне
        queryset = queryset.prefetch_related("year__exceptions")

        params = self.request.query_params
        class_id = params.get("class")
        if class_id:
            queryset = (
                queryset.filter(school_class_id=class_id)
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

    def copy_one_class(self, school_class, data, study_dates):
        """
        Копирование для одного класса. Вызывается внутри транзакции, потому
        что уроки, созданные предыдущим классом, занимают номера для следующего.
        """
        target = (data["target_start"], data["target_end"])
        year = school_class.year

        source_numbers = defaultdict(list)
        source_slots = self.own_slots().filter(
            school_class=school_class,
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
            # заменяем только обычные уроки: отменённые и дополнительные
            # — это ручная правка, её сносить нельзя
            deleted, _ = LessonSlot.objects.filter(
                school_class=school_class,
                date__range=target,
                is_extra=False,
                is_cancelled=False,
            ).delete()

        occupied = set(
            LessonSlot.objects.filter(
                school_class=school_class, date__range=target
            ).values_list("date", "lesson_number")
        )

        # номера, занятые другими классами того же учителя: он не может
        # вести два урока одновременно, такие слоты пропускаем с отчётом
        busy = {
            (slot.date, slot.lesson_number): slot.school_class.name
            for slot in LessonSlot.objects.filter(
                school_class__owner_id=year.owner_id,
                year=year,
                date__range=target,
                is_cancelled=False,
            )
            .exclude(school_class=school_class)
            .select_related("school_class")
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
                    school_class=school_class,
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
        Повторить раскладку периода-источника на целевом периоде.

        Без `class_id` копируется расписание целиком: все классы владельца,
        чей учебный год задевает цель. Отменённые и дополнительные уроки не
        копируются ни в том, ни в другом режиме.
        """
        form = CopySerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        data = form.validated_data

        one = data.get("school_class")
        if one is not None:
            classes = [one]
        else:
            classes = list(
                SchoolClass.objects.filter(
                    owner=request.user,
                    year__start_date__lte=data["target_end"],
                    year__end_date__gte=data["target_start"],
                ).select_related("year")
            )

        totals = {"created": 0, "skipped": 0, "deleted": 0, "conflicts": []}
        study_by_year = {}

        with transaction.atomic():
            for school_class in classes:
                year = school_class.year
                if year.pk not in study_by_year:
                    # учебные дни считает calendars — здесь мы их только спрашиваем
                    study_by_year[year.pk] = {
                        day.date for day in year.build_days() if day.is_study
                    }

                result = self.copy_one_class(
                    school_class, data, study_by_year[year.pk]
                )
                for key in ("created", "skipped", "deleted"):
                    totals[key] += result[key]
                totals["conflicts"].extend(result["conflicts"])

        return Response(totals)

    @action(detail=False, methods=["delete"])
    def bulk(self, request):
        """Снести уроки класса за период."""
        params = request.query_params
        form = BulkDeleteSerializer(
            data={
                "school_class": params.get("class"),
                "start": params.get("start"),
                "end": params.get("end"),
                "only_regular": params.get("only_regular", False),
            },
            context=self.get_serializer_context(),
        )
        form.is_valid(raise_exception=True)
        data = form.validated_data

        queryset = self.own_slots().filter(
            school_class=data["school_class"],
            date__range=(data["start"], data["end"]),
        )
        if data["only_regular"]:
            # ручная разметка переживает массовую чистку
            queryset = queryset.filter(is_extra=False, is_cancelled=False)

        deleted, _ = queryset.delete()
        return Response({"deleted": deleted})

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        """
        Сводное расписание за период: все классы владельца сразу.

        Уроки сгруппированы по датам, рядом — разметка дней: учебный ли
        день и как называется исключение. Даты, не попавшие ни в один
        учебный год, помечены статусом outside.
        """
        form = PeriodSerializer(data=request.query_params)
        form.is_valid(raise_exception=True)
        start, end = form.validated_data["start"], form.validated_data["end"]

        lessons = defaultdict(list)
        slots = (
            self.own_slots()
            .filter(date__range=(start, end))
            .select_related("school_class")
        )
        for slot in slots:
            lessons[slot.date.isoformat()].append(
                {
                    "id": slot.id,
                    "lesson_number": slot.lesson_number,
                    "class_id": slot.school_class_id,
                    "class_name": slot.school_class.name,
                    "is_cancelled": slot.is_cancelled,
                    "is_extra": slot.is_extra,
                    "reason": slot.reason,
                }
            )

        # разметку берём из календаря: год знает про каникулы и переносы
        days = {
            day.isoformat(): {
                "status": "outside",
                "title": "вне учебного года",
                "is_study": False,
            }
            for day in calendar_services.iter_dates(start, end)
        }
        years = SchoolYear.objects.filter(
            owner=request.user, start_date__lte=end, end_date__gte=start
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
        """Сколько уроков всего, прошло, осталось, отменено и добавлено."""
        queryset = self.own_slots()

        class_id = request.query_params.get("class")
        if class_id:
            queryset = (
                queryset.filter(school_class_id=class_id)
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
