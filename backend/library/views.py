from config.access import IsSchoolMember, IsTeacher, SchoolScopedViewSet
from config.errors import Codes, api_denied, api_error
from django.db import transaction
from django.db.models import Prefetch
from files.models import Attachment
from files.serializers import with_sharing
from plans import services as plan_services
from plans.views import refuse_if_taught_lost
from plans.content import CONTENT_FIELDS
from plans.models import PlanNode
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import PlanTemplate
from .serializers import (
    FromPlanSerializer,
    PlanTemplateDetailSerializer,
    PlanTemplateSerializer,
    TemplateRowSerializer,
    UpdateFromPlanSerializer,
    UseTemplateSerializer,
    visible_templates,
)


class IsAuthorOrReadOnly(BasePermission):
    """
    Anybody in the school may read and may put something new on the shelf.

    Changing an entry is the author's alone — an administrator who could
    rewrite a colleague's plan would make authorship meaningless. Removing
    is the one thing an administrator may also do: the library is the
    school's and somebody has to be able to clear out rubbish.
    """

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        if request.method == "DELETE" and user.is_school_admin:
            return True
        if obj.author_id == user.pk:
            return True

        api_denied(
            Codes.NOT_TEMPLATE_AUTHOR,
            "Only the author can change this plan. Take a copy and edit that.",
        )


class PlanTemplateViewSet(SchoolScopedViewSet):
    """
    The school's shelf of lesson plans.

    A school object, so it goes through `SchoolScopedViewSet` and its school
    filter — but not through its admin-for-write rule: writing here is about
    authorship, not about the role, so the permissions are replaced.

    Drafts are filtered out of the queryset rather than hidden by a check:
    a draft somebody else wrote must be as absent as a template from another
    school, in the list and in every foreign key that names one.
    """

    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsAuthorOrReadOnly,
    ]
    queryset = PlanTemplate.objects.select_related("subject", "author")

    def get_serializer_class(self):
        if self.action in ("retrieve", "from_plan"):
            return PlanTemplateDetailSerializer
        return PlanTemplateSerializer

    def get_queryset(self):
        queryset = visible_templates(self.request.user).select_related(
            "subject", "author"
        )

        # Строки и их вложения тянутся только при просмотре одного шаблона:
        # список их не показывает, а запрос на строку стоил сорока восьми
        # лишних на шаблон в полсотни уроков — и это на кнопку «Посмотреть»
        # в полке, то есть на обычное действие.
        #
        # Только `retrieve`, и это важно: `update-from-plan` перезаписывает
        # строки после `get_object()`, и предвыбранный кэш показал бы в
        # ответе старые.
        if self.action == "retrieve":
            # именно `Prefetch` с готовым `with_sharing`: сериализатор строки
            # просит вложения уже посчитанными, а всякий `annotate` поверх
            # менеджера кэш предвыборки отбрасывает и снова идёт в базу
            queryset = queryset.prefetch_related(
                Prefetch(
                    "rows__attachments",
                    queryset=with_sharing(Attachment.objects.all()),
                )
            )

        params = self.request.query_params

        for param, lookup in (("subject", "subject_id"), ("grade", "grade")):
            raw = params.get(param)
            if not raw:
                continue
            queryset = (
                queryset.filter(**{lookup: raw}) if raw.isdigit() else queryset.none()
            )

        if params.get("mine") in ("true", "1"):
            queryset = queryset.filter(author=self.request.user)

        return queryset

    def perform_create(self, serializer):
        # a new entry always starts as the author's draft: publishing is a
        # separate, deliberate step
        serializer.save(
            school=self.request.user.school,
            author=self.request.user,
            is_published=serializer.validated_data.get("is_published", False),
        )

    @action(detail=False, methods=["post"], url_path="from-plan")
    def from_plan(self, request):
        """
        Put the plan of a course onto the shelf, as a draft.

        A snapshot, not a link: what happens to the course plan afterwards
        does not reach the template, and vice versa.
        """
        form = FromPlanSerializer(data=request.data, context={"request": request})
        form.is_valid(raise_exception=True)
        data = form.validated_data

        rows = services.plan_as_rows(data["course"].pk)
        if not rows:
            api_error(
                Codes.PLAN_EMPTY,
                "There is nothing to publish: the plan of this course is empty.",
                field="course",
            )

        with transaction.atomic():
            template = PlanTemplate.objects.create(
                school=request.user.school,
                subject=data["subject"],
                grade=data["grade"],
                title=data["title"],
                description=data["description"],
                author=request.user,
                is_published=False,
            )
            services.write_rows(template, rows)

        return Response(
            PlanTemplateDetailSerializer(
                template, context=self.get_serializer_context()
            ).data,
            status=201,
        )

    @action(detail=True, methods=["post"], url_path="update-from-plan")
    def update_from_plan(self, request, pk=None):
        """
        Refresh the shelf copy from a course plan. The author only.

        Nobody who has already taken a copy is affected — their plan stopped
        being connected the moment they took it.

        Курс при этом **любой свой**, не обязательно тот, с которого шаблон
        сняли. Так и надо: курс привязан к учебному году, в сентябре «9Б
        Алгебра» — уже другая запись, и обновлять полку с неё — обычный
        годовой цикл. Ограничение «только исходный курс» сломало бы ровно
        его.

        Предмет и год берутся у курса заново — тем же правилом, что при
        снятии. Иначе они замерзали бы в момент публикации: администратор
        поправил год обучения параллели, автор нажал «Обновить», строки
        переписались, а на полке шаблон остался под старым годом, и найти
        его по фильтру стало нельзя.
        """
        template = self.get_object()
        self.check_object_permissions(request, template)

        form = UpdateFromPlanSerializer(data=request.data, context={"request": request})
        form.is_valid(raise_exception=True)

        course = form.validated_data["course"]
        rows = services.plan_as_rows(course.pk)
        if not rows:
            api_error(
                Codes.PLAN_EMPTY,
                "There is nothing to publish: the plan of this course is empty.",
                field="course",
            )

        # у курса, заведённого до справочников, спрашивать нечего — тогда у
        # шаблона остаётся то, что назвали при публикации
        moved = {}
        if course.subject_id and course.subject_id != template.subject_id:
            moved["subject"] = course.subject
        if course.grade and course.grade.level != template.grade:
            moved["grade"] = course.grade.level

        # обе записи одной транзакцией: строки уже свежие, а предмет и год
        # ещё старые — состояние, которого никто потом не объяснит, и найти
        # такой шаблон по фильтру нельзя
        with transaction.atomic():
            services.write_rows(template, rows)
            if moved:
                for field, value in moved.items():
                    setattr(template, field, value)
                template.save(update_fields=list(moved))

        return Response(
            PlanTemplateDetailSerializer(
                template, context=self.get_serializer_context()
            ).data
        )

    @action(detail=True, methods=["put"])
    def rows(self, request, pk=None):
        """
        Replace the lines of a template in one go. The author only.

        A whole-list write rather than per-row endpoints: the list is flat
        and short, and positions have no other source of truth than the
        order they arrive in — so there is nothing to renumber and no way to
        leave a gap. Per-row editing would need a second copy of the
        trickiest code in `plans/services.py` for a shape that has no nesting.
        """
        template = self.get_object()
        self.check_object_permissions(request, template)

        form = TemplateRowSerializer(data=request.data, many=True)
        form.is_valid(raise_exception=True)

        # a line that names the row it came from keeps that row's files: the
        # write replaces every row, and without this the attachments would go
        # with them
        carried = {
            row.pk: list(row.attachments.all())
            for row in template.rows.prefetch_related("attachments")
        }

        rows = [
            plan_services.ImportedRow(
                is_section=row["is_header"],
                title=row["title"],
                note=row.get("note", ""),
                content={field: row.get(field, "") for field in CONTENT_FIELDS},
                attachments=carried.get(row.get("id"), ()),
            )
            for row in form.validated_data
        ]
        services.write_rows(template, rows)

        return Response(
            PlanTemplateDetailSerializer(
                template, context=self.get_serializer_context()
            ).data
        )


class ImportFromTemplateView(APIView):
    """
    Take a template into a course plan.

    The teacher's own plan for that course is what gets written, through the
    same `apply_import` the CSV import uses. One transaction: a half-copied
    plan is worse than none.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def post(self, request):
        form = UseTemplateSerializer(data=request.data, context={"request": request})
        form.is_valid(raise_exception=True)
        data = form.validated_data

        # полка пишет в план тем же `apply_import`, а значит и сносит его
        # так же: без этой проверки шаблон уносил бы записи о занятиях —
        # ровно то, за что отказывает импорт файлом
        if data["mode"] != "append":
            refuse_if_taught_lost(
                data["course"], plan_services.plan_nodes(data["course"].pk)
            )

        result = services.import_into_course(
            template=data["template"],
            course_id=data["course"].pk,
            append=data["mode"] == "append",
        )

        return Response(result)
