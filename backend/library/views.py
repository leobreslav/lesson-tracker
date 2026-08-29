from config.access import IsSchoolMember, IsTeacher, SchoolScopedViewSet
from config.errors import Codes, api_denied, api_error
from django.db import transaction
from django.db.models import Prefetch
from files.models import Attachment
from files.serializers import with_sharing
from plans import history as plan_history
from plans import services as plan_services
from plans import views as plan_views
from plans.views import refuse_if_taught_lost
from plans.content import CONTENT_FIELDS
from plans.models import PlanNode
from plans.owning import of_course, of_template
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
                    "nodes__attachments",
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

    def live_template(self, subject, grade):
        """Мой живой шаблон по этому предмету и параллели, если он есть."""
        return PlanTemplate.objects.filter(
            school=self.request.user.school,
            author=self.request.user,
            subject=subject,
            grade=grade,
            is_live=True,
        ).first()

    @action(detail=False, methods=["post"], url_path="from-plan")
    def from_plan(self, request):
        """
        Put the plan of a course onto the shelf.

        Копия плана, а не связь с ним: что случится с планом курса дальше, до
        шаблона не доходит, и наоборот.

        **Видимость спрашивается сразу.** Раньше сюда всегда клали
        черновиком, а «Опубликовать» жило отдельной кнопкой в окне полки —
        то есть класть на полку и класть **на общую** полку было двумя
        действиями в разных местах, и второе легко забывалось. Черновик
        никуда не делся: это ответ «пока только себе».

        **`is_live` отвечает на другой вопрос — «веду или кладу снимком».**
        Живой по предмету и параллели один, поэтому второй отклоняется, а не
        отбирает пометку у прежнего: отобрать её молча значит превратить
        чужую работу в снимок, о котором никто не просил. Обновить уже
        лежащий живой — это `update-from-plan`, и кнопка для этого своя.
        """
        form = FromPlanSerializer(data=request.data, context={"request": request})
        form.is_valid(raise_exception=True)
        data = form.validated_data

        if data["is_live"]:
            standing = self.live_template(data["subject"], data["grade"])
            if standing is not None:
                api_error(
                    Codes.TEMPLATE_ALREADY_LIVE,
                    f"«{standing.title}» is already the template you keep up to "
                    "date for this subject and grade. Refresh it, or save a copy.",
                    field="is_live",
                    title=standing.title,
                    id=standing.pk,
                )

        rows = services.plan_as_rows(of_course(data["course"]))
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
                is_published=data["is_published"],
                is_live=data["is_live"],
            )
            services.write_rows(template, rows)

        return Response(
            PlanTemplateDetailSerializer(
                template, context=self.get_serializer_context()
            ).data,
            status=201,
        )

    @action(detail=True, methods=["get"], url_path="diff-from-plan")
    def diff_from_plan(self, request, pk=None):
        """
        Что станет с шаблоном, если обновить его планом курса.

        Спрашивается **до** нажатия и ничего не пишет. Раньше «Обновить»
        переписывало строки молча — и это было безопасно ровно потому, что
        шаблон был снимком плана и своей работы в нём не было. Теперь она
        там есть: план на полке пишут руками, и обновление с курса способно
        стереть написанное.

        Отказываться от обновления при этом незачем — годовой цикл «вёл год,
        обновил полку» никуда не делся, — а вот показать, что уйдёт, надо.
        Плюс снимок перед записью: `update-from-plan` берёт его, и ошибка
        отменяется одной кнопкой.
        """
        template = self.get_object()
        self.check_object_permissions(request, template)

        form = UpdateFromPlanSerializer(data=request.query_params, context={"request": request})
        form.is_valid(raise_exception=True)

        return Response(
            plan_views.overwrite_payload(
                of_template(template), of_course(form.validated_data["course"])
            )
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

        # Снимок не переписывают — он затем и снимок, и это единственное, что
        # он обещает. Обещание должно держаться и тогда, когда id пришёл не с
        # нашей кнопки: проверка во вьюхе — и есть то место, где оно живёт.
        # Передумали — сначала перевесьте пометку (`keep-updating`), и тогда
        # прежний живой станет снимком видимо, а не заодно.
        if not template.is_live:
            api_error(
                Codes.TEMPLATE_IS_A_SNAPSHOT,
                f"«{template.title}» is a copy left as it was. Make it the one "
                "you keep up to date before refreshing it.",
                field="id",
                title=template.title,
            )

        form = UpdateFromPlanSerializer(data=request.data, context={"request": request})
        form.is_valid(raise_exception=True)

        course = form.validated_data["course"]
        rows = services.plan_as_rows(of_course(course))
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

        # Переезд предмета или года умеет столкнуть шаблон с **другим** моим
        # живым: веду алгебру за восьмой и за девятый, обновляю восьмой с
        # курса, которому администратор поправил параллель, — и живых по
        # алгебре за девятый становится два. База это поймает ограничением,
        # но ответит отказом, в котором человеку нет ничего; спрашиваем сами.
        if moved:
            standing = self.live_template(
                moved.get("subject", template.subject),
                moved.get("grade", template.grade),
            )
            if standing is not None and standing.pk != template.pk:
                api_error(
                    Codes.TEMPLATE_ALREADY_LIVE,
                    f"This course moved the template to a subject and grade where "
                    f"«{standing.title}» is already the one you keep up to date.",
                    field="course",
                    title=standing.title,
                    id=standing.pk,
                )

        # обе записи одной транзакцией: строки уже свежие, а предмет и год
        # ещё старые — состояние, которого никто потом не объяснит, и найти
        # такой шаблон по фильтру нельзя
        # снимок до записи: обновление с курса теперь способно стереть
        # написанное руками, и ошибка обязана отменяться одной кнопкой. Стоит
        # он внутри той же транзакции — отказ записи обязан унести и снимок,
        # иначе в журнале остаётся шаг несостоявшегося обновления
        with transaction.atomic():
            plan_history.take(
                of_template(template), request.user, "template_refresh", course.name
            )
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

    @action(detail=True, methods=["post"], url_path="keep-updating")
    def keep_updating(self, request, pk=None):
        """
        Перевесить пометку: вести дальше **этот** шаблон, а не прежний.

        Живой по предмету и параллели один, поэтому действие ровно одно на
        две записи: пометка снимается с прежнего и ставится сюда, обе — в
        транзакции. Двумя запросами это было бы состояние «живых ноль» или
        «живых два» между ними; второе ограничение и не пустит.

        Зачем оно вообще. Копию кладут снимком, и обычно снимок так и лежит,
        но бывает наоборот: «вот эта версия удачнее, дальше веду её». Без
        такого действия ответом было бы «снимите шаблон заново», то есть
        третья запись на полке ради переезда пометки.

        Прежний живой при этом **становится снимком**, а не исчезает: его
        уже могли взять коллеги, и он остаётся тем, чем был, — планом,
        который кто-то положил на полку.
        """
        template = self.get_object()
        self.check_object_permissions(request, template)

        if template.is_live:
            # не отказ: просили состояние, а оно уже такое
            return Response(
                PlanTemplateDetailSerializer(
                    template, context=self.get_serializer_context()
                ).data
            )

        standing = self.live_template(template.subject, template.grade)

        with transaction.atomic():
            if standing is not None:
                standing.is_live = False
                standing.save(update_fields=["is_live"])

            template.is_live = True
            template.save(update_fields=["is_live"])

        return Response(
            PlanTemplateDetailSerializer(
                template, context=self.get_serializer_context()
            ).data
        )

    @action(detail=True, methods=["put"])
    def rows(self, request, pk=None):
        """
        Заменить план шаблона списком целиком. Только автор.

        Запись целиком, а не по строке, и это по-прежнему не наследство
        плоского хранения. Построчная правка у шаблона теперь тоже есть —
        обычной ручкой плана (`/api/plan/?template=`), — но это другой
        вопрос: там правят одну строку, здесь заменяют весь список разом,
        и у списка нет другого источника правды о порядке, кроме того, в
        каком он приехал.
        """
        template = self.get_object()
        self.check_object_permissions(request, template)

        form = TemplateRowSerializer(data=request.data, many=True)
        form.is_valid(raise_exception=True)

        # a line that names the row it came from keeps that row's files: the
        # write replaces every row, and without this the attachments would go
        # with them
        carried = {
            node.pk: list(node.attachments.all())
            for node in template.nodes.prefetch_related("attachments")
        }

        rows = [
            plan_services.ImportedRow(
                is_section=row["is_section"],
                title=row["title"],
                note=row.get("note", ""),
                content={field: row.get(field, "") for field in CONTENT_FIELDS},
                attachments=carried.get(row.get("id"), ()),
                # плоский список ничего не вкладывает: урок ложится в
                # последний виденный заголовок, как и при импорте файлом
                at_top_level=False,
            )
            for row in form.validated_data
        ]
        with transaction.atomic():
            plan_history.take(
                of_template(template), request.user, "rows", template.title
            )
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
                data["course"], plan_services.plan_nodes(of_course(data["course"]))
            )

        # снимок до записи: полка сносит план так же, как импорт файлом, и
        # отменяться это должно так же — одним нажатием
        #
        # Взятый блок назван в журнале своим словом: «взятие плана из
        # библиотеки» у кнопки отмены обещало бы не то — план на месте, а
        # отменяются пять дописанных уроков.
        #
        # Транзакция вокруг обоих: строка чужого шаблона отклоняется отказом
        # (`template_row_unknown`), и снимок, снятый до него, пережил бы
        # отказ — в журнале остался бы шаг взятия, которого не было.
        rows = data.get("rows")
        with transaction.atomic():
            plan_history.take(
                of_course(data["course"]),
                request.user,
                "template_part" if rows else f"template_{data['mode']}",
                data["template"].title,
            )

            result = services.import_into_course(
                template=data["template"],
                course_id=data["course"].pk,
                append=data["mode"] == "append",
                rows=rows,
            )

        return Response(result)
