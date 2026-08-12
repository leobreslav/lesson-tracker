from urllib.parse import quote

from config.access import IsSchoolMember, TeacherScopedViewSet
from config.errors import Codes, api_error
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from schedule.models import Course, LessonSlot

from . import services
from .models import PlanNode
from .serializers import (
    MoveSerializer,
    MoveToSerializer,
    PlanNodeCreateSerializer,
    PlanNodeUpdateSerializer,
    check_structure,
    flat_payload,
    layout_payload,
    tree_payload,
)


# a plan file over a megabyte is not a lesson plan any more
MAX_IMPORT_BYTES = 1024 * 1024


def read_date(value):
    """A date from a query parameter. Garbage is None, not a 500."""
    try:
        return parse_date(value or "")
    except ValueError:
        # parse_date raises on «2026-13-45»: the shape fits, the date does not
        return None


def perform_move(node, data) -> Response:
    form = MoveSerializer(data=data)
    form.is_valid(raise_exception=True)

    with transaction.atomic():
        moved = services.move(node, form.validated_data["direction"])

    # False means the node hit the edge of the tree; that is not an error
    return Response({"moved": moved})


class PlanNodeViewSet(TeacherScopedViewSet):
    """
    A teacher's plan inside a course.

    The list returns the whole tree rather than a flat set of nodes: without
    order and nesting it is useless.
    """

    queryset = PlanNode.objects.select_related("course", "parent")

    def get_serializer_class(self):
        if self.action == "create":
            return PlanNodeCreateSerializer
        return PlanNodeUpdateSerializer

    def requested_course(self):
        """
        The course from ?course=, limited to the requester's school.

        A course of another school is a 404 — the plan inside it is personal
        anyway, but the course itself must not even be namable.
        """
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

    def owner_of(self, course):
        """Whose plan in which course — everything below needs the pair."""
        return services.PlanOwner(
            teacher_id=self.request.user.pk, course_id=course.pk
        )

    def list(self, request, *args, **kwargs):
        return Response(tree_payload(self.owner_of(self.requested_course())))

    @action(detail=False, methods=["get"])
    def flat(self, request):
        """Only the lessons, in order — the sequence the schedule will get."""
        return Response(flat_payload(self.owner_of(self.requested_course())))

    def layout_entries(self, course):
        """Matching the plan to the schedule. Queries here, maths in services."""
        slots = LessonSlot.objects.filter(
            teacher=self.request.user, course=course, is_cancelled=False
        ).order_by("date", "lesson_number")

        return services.build_layout(
            services.flatten_lessons(self.owner_of(course)),
            list(slots),
            course.year.terms.all(),
        )

    @action(detail=False, methods=["get"])
    def layout(self, request):
        """
        Раскладка целиком или за период.

        Период режет уже посчитанную раскладку: сопоставление всегда идёт по
        всему плану и всему расписанию, иначе номера поехали бы.
        """
        entries = self.layout_entries(self.requested_course())

        start, end = (read_date(request.query_params.get(name)) for name in ("from", "to"))
        if start or end:
            entries = [
                entry
                for entry in entries
                if entry.slot is not None
                and (start is None or entry.slot.date >= start)
                and (end is None or entry.slot.date <= end)
            ]

        return Response(layout_payload(entries))

    @action(
        detail=False,
        methods=["get"],
        url_path="layout/agenda",
        url_name="layout-agenda",
    )
    def layout_agenda(self, request):
        """
        Темы уроков сразу по всем классам за период: slot_id → урок плана.

        Сводному расписанию иначе пришлось бы спрашивать раскладку по
        каждому классу отдельно. Сопоставление, как и всегда, считается по
        всему плану и всему расписанию класса, а период только режет ответ.
        """
        start = read_date(request.query_params.get("start"))
        end = read_date(request.query_params.get("end"))
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

        # courses where this teacher has anything at all in the period
        courses = Course.objects.filter(
            slots__teacher=request.user,
            slots__date__range=(start, end),
            slots__is_cancelled=False,
        ).distinct()

        slots = {}
        for course in courses:
            for entry in self.layout_entries(course):
                if entry.slot is None or entry.lesson is None:
                    continue
                if not start <= entry.slot.date <= end:
                    continue

                lesson = entry.lesson
                slots[entry.slot.pk] = {
                    "plan_row_id": lesson.node.pk,
                    "title": lesson.node.title,
                    "section_title": lesson.section.title if lesson.section else None,
                }

        return Response({"start": start, "end": end, "slots": slots})

    @action(detail=False, methods=["post"], url_path="import", url_name="import")
    def import_csv(self, request):
        """
        Импорт плана из CSV. Либо файл заезжает целиком, либо ничего.

        Разбор идёт до транзакции: непригодный файл не должен успеть снести
        существующий план в режиме replace.
        """
        course = self.requested_course()

        upload = request.FILES.get("file")
        if upload is None:
            api_error(Codes.FILE_REQUIRED, "A CSV file is required.", field="file")
        if upload.size > MAX_IMPORT_BYTES:
            api_error(
                Codes.FILE_TOO_LARGE,
                f"The file is larger than {MAX_IMPORT_BYTES // 1024 // 1024} MB.",
                field="file",
                limit_mb=MAX_IMPORT_BYTES // 1024 // 1024,
            )

        mode = request.data.get("mode", "replace")
        if mode not in ("replace", "append"):
            api_error(
                Codes.MODE_INVALID,
                "Mode must be either «replace» or «append».",
                field="mode",
            )

        try:
            rows, warnings = services.parse_plan_csv(
                services.decode_csv(upload.read())
            )
        except services.PlanImportError as error:
            api_error(Codes.FILE_UNREADABLE, str(error), field="file")

        with transaction.atomic():
            if mode == "replace":
                PlanNode.objects.filter(
                    teacher=request.user, course=course
                ).delete()

            created = services.apply_import(
                self.owner_of(course), rows, append=(mode == "append")
            )

        return Response(
            {
                "created_rows": created["headers"] + created["lessons"],
                "created_headers": created["headers"],
                "created_lessons": created["lessons"],
                "warnings": warnings,
            }
        )

    @action(detail=False, methods=["get"], url_path="export", url_name="export")
    def export_csv(self, request):
        """Выгрузка плана в CSV — формат тот же, что понимает импорт."""
        course = self.requested_course()
        content = services.build_plan_csv(services.get_tree(self.owner_of(course)))

        name = f"план_{course.name}_{timezone.localdate()}.csv"
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        # имя с кириллицей — только через RFC 5987, плюс ascii-запасное
        response["Content-Disposition"] = (
            'attachment; filename="plan.csv"; '
            f"filename*=UTF-8''{quote(name)}"
        )
        return response

    @action(detail=False, methods=["get"], url_path="layout/summary", url_name="layout-summary")
    def layout_summary(self, request):
        course = self.requested_course()
        cancelled = LessonSlot.objects.filter(
            teacher=request.user, course=course, is_cancelled=True
        ).count()

        return Response(
            services.layout_summary(
                self.layout_entries(course),
                today=timezone.localdate(),
                cancelled_count=cancelled,
                terms=course.year.terms.all(),
            )
        )

    def destroy(self, request, *args, **kwargs):
        node = self.get_object()
        # by default the content survives: lessons surface to the top level
        keep_children = request.query_params.get("keep_children", "true").lower() not in (
            "false",
            "0",
        )

        with transaction.atomic():
            if node.is_section and keep_children:
                services.dissolve_section(node)
            else:
                parent_id = node.parent_id
                # the node is needed as the (teacher, course) pair afterwards
                node.delete()
                services.reindex(node, parent_id)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """One step up or down, entering sections and leaving them."""
        return perform_move(self.get_object(), request.data)

    @action(detail=True, methods=["post"])
    def move_to(self, request, pk=None):
        """An explicit move, for when stepping is inconvenient."""
        node = self.get_object()

        form = MoveToSerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        parent = form.validated_data["parent"]

        if parent is not None and parent.course_id != node.course_id:
            api_error(
                Codes.PARENT_OTHER_CLASS,
                "That section belongs to another course.",
                field="parent",
            )
        check_structure(node, parent)

        with transaction.atomic():
            services.place(node, parent, form.validated_data["position"])

        return Response({"moved": True})


class SectionMoveView(APIView):
    """Moving a whole section against its neighbours on the top level."""

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def post(self, request, pk):
        section = get_object_or_404(
            PlanNode.objects.filter(teacher=request.user, is_section=True), pk=pk
        )
        return perform_move(section, request.data)
