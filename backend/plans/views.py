from urllib.parse import quote

from config.access import IsSchoolMember, TeacherScopedViewSet
from config.errors import Codes, api_error, error_payload
from django.db import transaction
from files import services as file_services
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
from calendars.models import DayException
from schedule.models import Course, LessonSlot

from . import services, xlsx
from .models import PlanNode
from .serializers import (
    MoveSerializer,
    MoveToSerializer,
    PlanNodeCreateSerializer,
    PlanNodeDetailSerializer,
    PlanNodeUpdateSerializer,
    check_structure,
    flat_payload,
    layout_payload,
    tree_payload,
)


# a plan file over a megabyte is not a lesson plan any more
MAX_IMPORT_BYTES = 1024 * 1024

IMPORT_MODES = ("replace", "append", "sync")

# сколько уроков с содержанием перечислять поимённо: список нужен, чтобы
# узнать свою работу в лицо, а не чтобы прочитать двести строк
LOSS_LIMIT = 50


def loss_payload(nodes) -> dict:
    """
    Что именно пропадёт вместе с этими узлами.

    Содержание и вложения в CSV не выражаются, поэтому удаление строки — это
    единственное место, где работа теряется молча. Считаем её до того, как
    спросить подтверждение, и отдельно — файлы, у которых это была последняя
    ссылка: остальные переживут удаление, и пугать ими нечестно.
    """
    lessons = [node for node in nodes if not node.is_section]
    with_content = [node for node in lessons if node.has_content]
    with_files = [node for node in lessons if node.attachment_count]
    losing = sorted(
        {node.pk: node for node in with_content + with_files}.values(),
        key=lambda node: node.pk,
    )

    return {
        "delete_lessons": len(lessons),
        "delete_sections": len(nodes) - len(lessons),
        "with_content": len(with_content),
        "with_attachments": len(with_files),
        "files_lost": file_services.files_at_risk([node.pk for node in with_files]),
        "delete_with_content": [
            {
                "id": node.pk,
                "title": node.title,
                "has_content": node.has_content,
                "has_attachments": bool(node.attachment_count),
            }
            for node in losing[:LOSS_LIMIT]
        ],
    }


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
        # the panel opens one lesson at a time, and only then is the content
        # worth sending — the tree carries a flag instead
        if self.action in ("retrieve", "update", "partial_update"):
            return PlanNodeDetailSerializer
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

    @action(detail=False, methods=["get"], url_path="layout/slots",
            url_name="layout-slots")
    def layout_slots(self, request):
        """
        Лента слотов курса: даты, термы и каникулы между уроками.

        От плана не зависит, поэтому страница плана берёт её один раз, а
        дальше сшивает с планом у себя — и даты сдвигаются в тот же миг,
        когда урок добавили или перетащили.
        """
        course = self.requested_course()
        slots = LessonSlot.objects.filter(
            teacher=request.user, course=course, is_cancelled=False
        ).order_by("date", "lesson_number")
        breaks = course.year.exceptions.filter(
            kind=DayException.Kind.VACATION
        ).order_by("start_date")

        # учебные дни года нужны ради нумерации недель: каникулярная неделя
        # номера не получает, и счёт идёт по занятиям, а не по календарю
        study = [day.date for day in course.year.build_days() if day.is_study]

        return Response(
            {
                "slots": services.slot_ribbon(
                    list(slots), course.year.terms.all(), breaks, study_days=study
                )
            }
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

    def uploaded_bytes(self):
        """Байты присланного файла или коротко объяснённый отказ."""
        upload = self.request.FILES.get("file")
        if upload is None:
            api_error(Codes.FILE_REQUIRED, "A file is required.", field="file")
        if upload.size > MAX_IMPORT_BYTES:
            api_error(
                Codes.FILE_TOO_LARGE,
                f"The file is larger than {MAX_IMPORT_BYTES // 1024 // 1024} MB.",
                field="file",
                limit_mb=MAX_IMPORT_BYTES // 1024 // 1024,
            )
        return upload.name or "", upload.read()

    def unreadable(self, code, error, *, refusing):
        """
        Нечитаемый файл: импорту это отказ, предпросмотру — строка списка.

        Предпросмотр не отказывается ни от чего принципиально: он затем и
        нужен, чтобы человек прочитал, что не так, — а 400 в ответ на выбор
        файла он увидел бы только консолью браузера.
        """
        if refusing:
            api_error(code, str(error), field="file")
        return services.ParsedPlan([], [error_payload(code, str(error))])

    def read_upload(self, *, refusing=True):
        """CSV: байты → строки плана, или код `file_unreadable`."""
        _, data = self.uploaded_bytes()
        try:
            return services.parse_plan_csv(services.decode_csv(data)), {}
        except services.PlanImportError as error:
            return self.unreadable(Codes.FILE_UNREADABLE, error, refusing=refusing), {}

    def read_workbook(self, *, refusing=True):
        """
        xlsx: то же самое, но ячейки берёт openpyxl.

        Вторым значением едет то, что стоит сказать про саму книгу: имя
        листа и сколько листов осталось за бортом. Разбор структуры общий с
        CSV, поэтому здесь только чтение.
        """
        name, data = self.uploaded_bytes()
        try:
            book = xlsx.read_plan_xlsx(data, filename=name)
        except services.PlanImportError as error:
            return self.unreadable(Codes.FILE_NOT_XLSX, error, refusing=refusing), {}

        try:
            parsed = services.parse_plan_rows(book.rows)
        except services.PlanImportError as error:
            parsed = self.unreadable(Codes.FILE_UNREADABLE, error, refusing=refusing)

        return parsed, {"sheet": book.sheet, "sheets_ignored": book.sheets_ignored}

    def read_mode(self, parsed, *, refusing=True):
        """
        Режим обязателен: умолчания у разрушительной операции быть не должно.

        Раньше POST без поля означал replace — то есть «снести план» по
        умолчанию. Ни один вызов от интерфейса на это не полагался.

        `refusing=False` — для предпросмотра: он ни от чего не отказывается,
        «синхронизировать не с чем» там такая же строка списка, как
        остальные ошибки файла.
        """
        mode = self.request.data.get("mode")
        if not mode:
            api_error(
                Codes.MODE_REQUIRED,
                "Choose the mode: «replace», «append» or «sync».",
                field="mode",
            )
        if mode not in IMPORT_MODES:
            api_error(
                Codes.MODE_INVALID,
                "Mode must be one of «replace», «append», «sync».",
                field="mode",
            )
        if refusing and mode == "sync" and not any(
            row.node_id for row in parsed.rows
        ):
            api_error(
                Codes.CSV_NOTHING_TO_SYNC,
                "Nothing to sync with: not a single row carries an id.",
                field="file",
            )
        return mode

    def refuse(self, errors):
        """Отказ по первой ошибке — остальные человек уже видел в предпросмотре."""
        first = errors[0]
        api_error(
            first["code"], first["detail"], field="file", **first.get("params", {})
        )

    @action(detail=False, methods=["post"], url_path="import", url_name="import")
    def import_csv(self, request):
        """Импорт плана из CSV."""
        return self.run_import(*self.read_upload())

    @action(detail=False, methods=["post"], url_path="import-xlsx",
            url_name="import-xlsx")
    def import_xlsx(self, request):
        """Импорт плана из книги Excel — тем же путём, что и CSV."""
        return self.run_import(*self.read_workbook())

    def run_import(self, parsed, about):
        """
        Либо файл заезжает целиком, либо ничего.

        Разбор идёт до транзакции: непригодный файл не должен успеть снести
        существующий план в режиме replace.
        """
        request = self.request
        course = self.requested_course()
        if not parsed.ok:
            # файл читается строго: непонятная строка отклоняет его целиком,
            # и до плана дело не доходит вовсе
            self.refuse(parsed.errors)
        mode = self.read_mode(parsed)
        owner = self.owner_of(course)

        if mode == "sync":
            plan = services.plan_sync(owner, parsed.rows)
            if not plan.ok:
                # весь файл или ничего: применить половину значит оставить
                # человека разбираться, какую именно
                self.refuse(plan.errors)

            with transaction.atomic():
                done = services.apply_sync(owner, plan)

            return Response({**done, **about})

        with transaction.atomic():
            if mode == "replace":
                PlanNode.objects.filter(
                    teacher=request.user, course=course
                ).delete()

            created = services.apply_import(
                owner, parsed.rows, append=(mode == "append")
            )

        return Response(
            {
                "created_rows": created["headers"] + created["lessons"],
                "created_headers": created["headers"],
                "created_lessons": created["lessons"],
                **about,
            }
        )

    @action(detail=False, methods=["post"], url_path="import-preview",
            url_name="import-preview")
    def import_preview(self, request):
        """Что сделает импорт CSV, до того как он что-то сделает."""
        return self.run_preview(*self.read_upload(refusing=False))

    @action(detail=False, methods=["post"], url_path="import-preview-xlsx",
            url_name="import-preview-xlsx")
    def import_preview_xlsx(self, request):
        """
        То же для книги Excel.

        Клиент xlsx не разбирает (для этого нужна была бы вторая
        библиотека уже в браузере), поэтому «как файл прочитан» он узнаёт
        отсюда — и до импорта, а не после.
        """
        return self.run_preview(*self.read_workbook(refusing=False))

    def run_preview(self, parsed, about):
        """
        Ничего не пишет и ни от чего не отказывается: даже файл с ошибками
        синхронизации разбирается до конца, чтобы показать их все разом.
        """
        course = self.requested_course()
        mode = self.read_mode(parsed, refusing=False)
        owner = self.owner_of(course)

        errors = list(parsed.errors)
        new_sections = new_lessons = update = 0
        doomed = []

        if errors:
            # файл не прочитан — считать по нему нечего, показываем ошибки
            pass
        elif mode == "sync" and not any(row.node_id for row in parsed.rows):
            errors = [
                error_payload(
                    Codes.CSV_NOTHING_TO_SYNC,
                    "Nothing to sync with: not a single row carries an id.",
                )
            ]
        elif mode == "sync":
            plan = services.plan_sync(owner, parsed.rows)
            errors = plan.errors
            new_sections = sum(1 for row, _, _ in plan.create if row.is_section)
            new_lessons = len(plan.create) - new_sections
            update, doomed = len(plan.update), plan.delete
        else:
            new_sections, new_lessons = parsed.sections, parsed.lessons
            # append не удаляет ничего, replace — всё, что было
            doomed = list(services.plan_nodes(owner)) if mode == "replace" else []

        return Response(
            {
                "mode": mode,
                # строк в файле против уроков: расхождение и есть число
                # строк, которые не прочитались
                "rows": parsed.data_rows,
                "lessons": parsed.lessons,
                "sections": parsed.sections,
                "create": new_sections + new_lessons,
                "create_sections": new_sections,
                "create_lessons": new_lessons,
                "update": update,
                "delete": len(doomed),
                # можно ли вообще синхронизировать: у xlsx клиент этого сам
                # не знает — файл он не читает
                "syncable": any(row.node_id for row in parsed.rows),
                **loss_payload(doomed),
                "errors": errors,
                **about,
            }
        )

    @action(detail=False, methods=["get"], url_path="export", url_name="export")
    def export_csv(self, request):
        """Выгрузка плана в CSV — формат тот же, что понимает импорт."""
        course = self.requested_course()
        content = services.build_plan_csv(services.get_tree(self.owner_of(course)))

        return self.as_download(
            content, course, "csv", "text/csv; charset=utf-8"
        )

    @action(detail=False, methods=["get"], url_path="export-xlsx",
            url_name="export-xlsx")
    def export_xlsx(self, request):
        """
        Тот же план книгой Excel.

        Оформление (текстовый формат ячеек, закреплённая шапка, запертый
        столбец id) живёт в `plans/xlsx.py` — здесь только выдача файла.
        """
        course = self.requested_course()
        content = xlsx.build_plan_xlsx(services.get_tree(self.owner_of(course)))

        return self.as_download(
            content,
            course,
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def as_download(self, content, course, extension, content_type):
        """Файл под именем «план_<курс>_<дата>.<расширение>»."""
        name = f"план_{course.name}_{timezone.localdate()}.{extension}"
        response = HttpResponse(content, content_type=content_type)
        # имя с кириллицей — только через RFC 5987, плюс ascii-запасное
        response["Content-Disposition"] = (
            f'attachment; filename="plan.{extension}"; '
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
