from collections import Counter, defaultdict
from urllib.parse import quote

from config.access import (
    CourseScopedViewSet,
    IsSchoolMember,
    IsStudent,
    IsTeacher,
)
from config.errors import Codes, api_error, error_payload
from django.db import transaction
from django.db.models import Q
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
from rest_framework.viewsets import ReadOnlyModelViewSet
from calendars.models import DayException
from schedule.models import Course, Slot

from . import approval, progress, services, xlsx
from .models import PlanBaseline, PlanNode
from .serializers import (
    MoveSerializer,
    MoveToSerializer,
    PlanNodeCreateSerializer,
    PlanNodeDetailSerializer,
    PlanNodeUpdateSerializer,
    baseline_payload,
    check_structure,
    layout_payload,
    request_payload,
    review_payload,
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


def refuse_if_taught(node) -> None:
    """
    Проведённый урок с места не двигают.

    Раскладка теперь двухступенчатая: час со связью показывает свой урок, а
    остальные разбирают оставшиеся по порядку. Пока строка не связана,
    порядок — это всё, что о ней известно, и переставлять её можно свободно.
    Как только за ней записан час, позиция и запись начинают говорить
    разное, и переставленная строка вытесняет соседей неизвестно куда.

    Отказ мягкий по смыслу: двигается всё, что ниже последней связи, — а это
    и есть будущее, ради которого перетаскивание и заведено. У темы
    спрашивается то же самое про её уроки: перенос темы двигает их все.
    """
    from schedule.models import Slot

    taught = Slot.objects.filter(
        Q(lesson=node) | Q(lesson__parent=node)
    ).select_related("lesson").first()

    if taught is not None:
        api_error(
            Codes.PLAN_LESSON_TAUGHT,
            f"«{taught.lesson.title}» was taught on {taught.date}: a lesson "
            "already given keeps its place.",
            field="position",
            title=taught.lesson.title,
            date=str(taught.date),
        )


def perform_move(node, data) -> Response:
    form = MoveSerializer(data=data)
    form.is_valid(raise_exception=True)
    refuse_if_taught(node)

    with transaction.atomic():
        moved = services.move(node, form.validated_data["direction"])

    # False means the node hit the edge of the tree; that is not an error
    return Response({"moved": moved})


class PlanNodeViewSet(CourseScopedViewSet):
    """
    Учебный план курса.

    План принадлежит курсу, а не человеку: читает его всякий, кто в курсе
    работает, правит — назначенный ведущий учитель (`CourseScopedViewSet`).

    Список отдаёт дерево целиком, а не плоский набор узлов: без порядка и
    вложенности он бесполезен.
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

    def requested_course(self, *, write=False):
        """
        Курс из ?course=, только из своих.

        Чужой курс — 404, и не важно, своей он школы или чужой: план,
        расписание и работы принадлежат курсу, а курс — тому, кому его
        поручили. Действия без объекта на входе (импорт, экспорт, отправка
        на утверждение) идут мимо `get_object`, и другого общего места для
        этой проверки у них нет.

        `write` оставлен ради читаемости вызовов: он ничего не добавляет,
        пока читают и пишут одни и те же, — но говорит, что действие
        разрушительное.
        """
        raw = self.request.query_params.get("course")
        if not raw or not raw.isdigit():
            api_error(
                Codes.CLASS_REQUIRED,
                "The «course» query parameter with a course id is required.",
                field="course",
            )

        return get_object_or_404(self.my_courses(), pk=raw)

    def list(self, request, *args, **kwargs):
        return Response(tree_payload(self.requested_course().pk))

    def layout_entries(self, course):
        """
        Сопоставление плана с расписанием. Запросы здесь, арифметика в services.

        Слоты берутся **по курсу**, а не по себе. Курс ведёт один человек, но
        он мог смениться среди года, и тогда сентябрь лежит у предшественника:
        считая только свои, новый ведущий получал бы «в январе вас ждёт урок
        №1», то есть заново весь сентябрь. Расписание пока личное, а вот
        раскладка отвечает на вопрос курса — сколько его плана уже прошло.
        """
        slots = Slot.objects.filter(
            course=course, is_cancelled=False
        ).order_by("date", "lesson_number")

        return services.build_layout(
            services.flatten_lessons(course.pk),
            list(slots),
            course.year.terms.all(),
        )

    @action(detail=False, methods=["get"])
    def progress(self, request):
        """
        Как идут дела **по всем своим курсам сразу** — главная страница.

        План всегда про один курс, главная — про все: учитель ведёт пять и
        хочет одним взглядом понять, где проблема. Считает это `progress`,
        и тем же расчётом пользуется экран методиста: вопрос у них один, и
        двух ответов на него быть не должно.
        """
        return Response(
            {
                "courses": progress.rows_for(
                    progress.own_courses(request.user), timezone.localdate()
                )
            }
        )

    @action(detail=False, methods=["get"])
    def baseline(self, request):
        """
        Состояние эталона у этого плана: что утверждено и что на подходе.

        Один ответ на весь блок в интерфейсе: утверждённый снимок (и когда
        его утвердили), поданный или возвращённый запрос с замечанием, и
        список методистов, которым можно отправить, — иначе страница
        спрашивала бы это тремя запросами и показывала бы полусостояние.
        """
        course = self.requested_course()

        return Response(
            baseline_payload(
                approval.approved_baseline(course.pk),
                approval.open_request(course.pk),
                approval.methodists_for(course),
                subject=course.name,
            )
        )

    @action(detail=False, methods=["post"], url_path="baseline/submit",
            url_name="baseline-submit")
    def baseline_submit(self, request):
        """
        Отправить план на утверждение — со снимком, снятым **сейчас**.

        Методиста выбирает учитель, если их несколько; при единственном он
        подставляется сам. Ни одного — отказ с объяснением: молчаливое «не
        получилось» отправило бы человека искать ошибку у себя.
        """
        course = self.requested_course(write=True)
        methodists = approval.methodists_for(course)

        if not methodists:
            api_error(
                Codes.NO_METHODIST,
                f"Nobody approves the plan of «{course.name}» — ask the school "
                "administrator to name a methodist on the course card.",
                field="course",
                subject=course.name,
            )

        chosen = request.data.get("reviewer")
        if chosen is None and len(methodists) > 1:
            api_error(
                Codes.REVIEWER_REQUIRED,
                "This course has several methodists — choose one.",
                field="reviewer",
            )

        reviewer = next(
            (row.user for row in methodists if str(row.user_id) == str(chosen)),
            methodists[0].user if chosen is None else None,
        )
        if reviewer is None:
            api_error(
                Codes.NOT_A_METHODIST,
                "That person does not approve the plan of this course.",
                field="reviewer",
            )

        baseline = approval.submit(course, reviewer, request.user)

        return Response(
            baseline_payload(
                approval.approved_baseline(course.pk),
                baseline,
                methodists,
                subject=course.name,
            ),
            status=status.HTTP_201_CREATED,
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
        slots = Slot.objects.filter(
            course=course, is_cancelled=False
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

        # свои курсы, в которых за период вообще что-то есть
        courses = list(
            Course.objects.for_teacher(request.user)
            .filter(
                slots__date__range=(start, end),
                slots__is_cancelled=False,
            )
            .distinct()
            .select_related("year")
            .prefetch_related("year__terms")
        )

        # все выборки до цикла: запрос уходит на каждую навигацию по
        # расписанию и повторяется после любой правки, а курсов у учителя
        # пять. Расчёт при этом тот же самый — `build_layout` по всему плану
        # и всему расписанию курса, период только режет ответ
        lessons_by_course = services.lessons_by_course(
            [course.pk for course in courses]
        )

        slots_by_course = defaultdict(list)
        for slot in Slot.objects.filter(
            course__in=courses, is_cancelled=False
        ).order_by("date", "lesson_number"):
            slots_by_course[slot.course_id].append(slot)

        slots = {}
        for course in courses:
            entries = services.build_layout(
                lessons_by_course[course.pk],
                slots_by_course[course.pk],
                course.year.terms.all(),
            )
            for entry in entries:
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
        # право спрашивается до чтения файла: разбирать присланное у того,
        # кому сюда нельзя, незачем
        return self.run_import(self.requested_course(write=True), *self.read_upload())

    @action(detail=False, methods=["post"], url_path="import-xlsx",
            url_name="import-xlsx")
    def import_xlsx(self, request):
        """Импорт плана из книги Excel — тем же путём, что и CSV."""
        return self.run_import(
            self.requested_course(write=True), *self.read_workbook()
        )

    def run_import(self, course, parsed, about):
        """
        Либо файл заезжает целиком, либо ничего.

        Разбор идёт до транзакции: непригодный файл не должен успеть снести
        существующий план в режиме replace.
        """
        if not parsed.ok:
            # файл читается строго: непонятная строка отклоняет его целиком,
            # и до плана дело не доходит вовсе
            self.refuse(parsed.errors)
        mode = self.read_mode(parsed)

        if mode == "sync":
            plan = services.plan_sync(course.pk, parsed.rows)
            if not plan.ok:
                # весь файл или ничего: применить половину значит оставить
                # человека разбираться, какую именно
                self.refuse(plan.errors)

            with transaction.atomic():
                done = services.apply_sync(course.pk, plan)

            return Response({**done, **about})

        with transaction.atomic():
            if mode == "replace":
                PlanNode.objects.filter(course=course).delete()

            created = services.apply_import(
                course.pk, parsed.rows, append=(mode == "append")
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
            plan = services.plan_sync(course.pk, parsed.rows)
            errors = plan.errors
            new_sections = sum(1 for row, _, _ in plan.create if row.is_section)
            new_lessons = len(plan.create) - new_sections
            update, doomed = len(plan.update), plan.delete
        else:
            new_sections, new_lessons = parsed.sections, parsed.lessons
            # append не удаляет ничего, replace — всё, что было
            doomed = list(services.plan_nodes(course.pk)) if mode == "replace" else []

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
        content = services.build_plan_csv(services.get_tree(course.pk))

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
        content = xlsx.build_plan_xlsx(services.get_tree(course.pk))

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
        cancelled = Slot.objects.filter(
            course=course, is_cancelled=True
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
                # узел ещё нужен: по нему берут курс, чтобы перенумеровать
                node.delete()
                services.reindex(node.course_id, parent_id)

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
        refuse_if_taught(node)

        with transaction.atomic():
            services.place(node, parent, form.validated_data["position"])

        return Response({"moved": True})


class SectionMoveView(APIView):
    """Moving a whole section against its neighbours on the top level."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def post(self, request, pk):
        section = get_object_or_404(
            PlanNode.objects.filter(
                course__assignments__teacher=request.user, is_section=True
            ),
            pk=pk,
        )
        return perform_move(section, request.data)


class PlanReviewViewSet(ReadOnlyModelViewSet):
    """
    Экран методиста: **все** планы, которые он ведёт.

    Очередью на утверждение это было, и очередь оказалась слишком узкой:
    методист видел только тех, кто прислал план, и ровно ничего — про
    остальных. А спрашивают с него как раз про остальных: кто отстаёт, у
    кого план не помещается в год, кто переписал половину после
    утверждения. Поэтому список теперь полный, а ожидающий запрос — просто
    пометка в строке.

    Числа те же, что учитель видит у себя на главной, и считает их тот же
    `progress.rows_for`: методист и учитель должны смотреть на одно и то же,
    иначе разговор про «отстаёшь» начинается со спора о цифрах.

    Читать — и только: методист утверждает или возвращает, но не правит.
    Чужой план правится только его автором, и это не вопрос вежливости —
    иначе учитель однажды обнаружил бы у себя чужие уроки.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]
    serializer_class = None

    def get_queryset(self):
        """Для `retrieve`, `approve` и `return` — только поданные запросы."""
        return approval.review_queue(self.request.user)

    def get_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def list(self, request):
        return Response(
            {
                "plans": progress.rows_for(
                    progress.supervised_courses(request.user), timezone.localdate()
                )
            }
        )

    def retrieve(self, request, pk=None):
        baseline = self.get_object()
        course = baseline.course
        slots = Slot.objects.filter(course=course, is_cancelled=False).count()
        rows = services.plan_snapshot(course.pk)
        lessons = sum(1 for row in rows if not row.is_section)

        return Response(
            {
                **review_payload(baseline, rows=rows),
                # ключевые числа рядом с планом: методист смотрит не только
                # «что написано», но и «помещается ли это в год»
                "slots_total": slots,
                "reserve": slots - lessons,
            }
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        baseline = self.get_object()
        approval.approve(baseline, request.user)

        return Response(review_payload(baseline, rows=list(baseline.rows.all())))

    @action(detail=True, methods=["post"], url_path="return", url_name="return")
    def send_back(self, request, pk=None):
        """Возврат без замечания смысла не имеет: учителю нечего исправлять."""
        comment = (request.data.get("comment") or "").strip()
        if not comment:
            api_error(
                Codes.COMMENT_REQUIRED,
                "Say what to fix — a plan returned without a word is a riddle.",
                field="comment",
            )

        baseline = self.get_object()
        approval.send_back(baseline, request.user, comment)

        return Response(review_payload(baseline))


class StudentCourseView(APIView):
    """
    Курс глазами ученика: учебный план с датами.

    Плана у ученика раньше не было вовсе — он видел только название курса и
    список работ, — и на вопрос «что мы вообще проходим» ответить было
    нечем. Теперь план курса открыт: он **принадлежит курсу**, значит у
    ученика и учителя он один и тот же, и второй правды тут нет.

    Показываются только **названия**: цели, ход урока, домашнее задание и
    вложения остаются учительскими. Показывать их — отдельное решение, и
    принимать его надо не заодно.

    Год целиком, без окна: ученик спрашивает «что было и что будет», а не
    «что на этой неделе».

    Даты берутся той же раскладкой, что у учителя (`build_layout` по слотам
    **курса**), поэтому расходиться им негде. Урок, которому слота не
    хватило, приезжает без даты — врать про «не помещается» ученику
    незачем, это разговор учителя с методистом.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def get(self, request, pk):
        from schedule.models import Course, CourseStudent

        # строка зачисления и есть право видеть: снятый с курса читает
        # сделанное, поэтому берётся любая, а не только действующая
        enrolment = get_object_or_404(
            CourseStudent.objects.select_related(
                "course", "course__subject", "course__grade", "course__year"
            ).prefetch_related("course__year__terms"),
            student=request.user,
            course_id=pk,
            course__school_id=request.user.school_id,
        )
        course = enrolment.course

        slots = Slot.objects.filter(
            course=course, is_cancelled=False
        ).order_by("date", "lesson_number")
        lessons = services.flatten_lessons(course.pk)
        placed = {
            entry.lesson.node.pk: entry
            for entry in services.build_layout(
                lessons, list(slots), course.year.terms.all()
            )
            if entry.lesson is not None
        }

        today = timezone.localdate()
        teacher = (
            Course.objects.filter(pk=course.pk)
            .values_list("assignments__teacher__first_name",
                         "assignments__teacher__last_name",
                         "assignments__teacher__email")
            .first()
        )

        rows = []
        for branch in services.get_tree(course.pk):
            if branch.node.is_section:
                rows.append({"id": branch.node.pk, "is_section": True,
                             "title": branch.node.title})
                children = branch.children
            else:
                children = (branch.node,)

            for node in children:
                entry = placed.get(node.pk)
                slot = entry.slot if entry else None
                rows.append(
                    {
                        "id": node.pk,
                        "is_section": False,
                        "title": node.title,
                        "number": entry.lesson.number if entry else None,
                        "date": slot.date if slot else None,
                        "past": bool(slot and slot.date < today),
                        "term": entry.term.name if entry and entry.term else None,
                    }
                )

        return Response(
            {
                "course": {
                    "id": course.pk,
                    "name": course.name,
                    "subject": course.subject.name if course.subject else None,
                    "grade": course.grade.name if course.grade else None,
                    "active": enrolment.is_active,
                    "teacher": person_name(teacher),
                },
                "lessons": rows,
            }
        )


def person_name(row) -> str | None:
    """«Имя Фамилия», а нет — адрес; курс без ведущего даёт None."""
    if row is None or not any(row):
        return None

    first, last, email = row
    return f"{first or ''} {last or ''}".strip() or email
