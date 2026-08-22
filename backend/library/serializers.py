from config.errors import Codes, api_error
from plans.content import CONTENT_EXTRA_KWARGS, CONTENT_FIELDS, content_problems
from rest_framework import serializers
from schedule.models import Course, Subject
from schedule.serializers import teacher_courses

from .models import PlanTemplate, PlanTemplateRow


def school_subjects(serializer):
    """Subjects of the requester's school — another school's are invisible."""
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return Subject.objects.none()
    return Subject.objects.filter(school_id=user.school_id)


class TemplateRowSerializer(serializers.ModelSerializer):
    """
    One line of a template, both ways.

    `id` is writable on the way in, and only for one reason: the rows are
    rewritten as a whole list (see `services.write_rows`), which would
    otherwise drop the attachments of every row on every save. A line that
    names the row it came from keeps its files.
    """

    id = serializers.IntegerField(required=False)
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = PlanTemplateRow
        fields = (
            "id",
            "position",
            "is_header",
            "title",
            "note",
            *CONTENT_FIELDS,
            "attachments",
        )
        read_only_fields = ("position",)
        extra_kwargs = CONTENT_EXTRA_KWARGS

    def get_attachments(self, obj):
        """
        Вложения строки. Считанные заранее — берём как есть.

        `with_sharing` навешивает `annotate`, а он поверх предвыбранного
        менеджера означает новый запрос: у шаблона в полсотни строк это
        полсотни запросов на одно окно просмотра. Поэтому просмотр шаблона
        приносит их уже посчитанными (см. `PlanTemplateViewSet.get_queryset`),
        а поодиночке считаем только там, где предвыборки нет.
        """
        from files.serializers import AttachmentSerializer, with_sharing

        prefetched = getattr(obj, "_prefetched_objects_cache", {})
        rows = (
            obj.attachments.all()
            if "attachments" in prefetched
            else with_sharing(obj.attachments.all())
        )
        return AttachmentSerializer(rows, many=True).data

    def validate(self, attrs):
        problems = content_problems(
            is_section=attrs.get("is_header", False), values=attrs
        )
        for field, message in problems.items():
            api_error(Codes.CONTENT_ON_SECTION, message, field=field)
        return attrs


class PlanTemplateSerializer(serializers.ModelSerializer):
    """
    A template as the list shows it.

    `mine` and `can_edit` are computed here rather than left to the frontend:
    the rule about who may change what belongs on the server, and the
    interface only decides which buttons to draw.
    """

    subject_name = serializers.CharField(source="subject.name", read_only=True)
    author_name = serializers.SerializerMethodField()
    lessons = serializers.IntegerField(source="lesson_count", read_only=True)
    mine = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = PlanTemplate
        fields = (
            "id",
            "subject",
            "subject_name",
            "grade",
            "title",
            "description",
            "author",
            "author_name",
            "is_published",
            "lessons",
            "mine",
            "can_edit",
            "can_delete",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "author", "created_at", "updated_at")

    def get_fields(self):
        fields = super().get_fields()
        fields["subject"].queryset = school_subjects(self)
        return fields

    def get_author_name(self, obj):
        if obj.author is None:
            return None
        full = f"{obj.author.first_name} {obj.author.last_name}".strip()
        return full or obj.author.email

    def requester(self):
        return self.context["request"].user

    def get_mine(self, obj):
        return obj.author_id == self.requester().pk

    def get_can_edit(self, obj):
        return obj.author_id == self.requester().pk

    def get_can_delete(self, obj):
        user = self.requester()
        return obj.author_id == user.pk or user.is_school_admin


class PlanTemplateDetailSerializer(PlanTemplateSerializer):
    rows = TemplateRowSerializer(many=True, read_only=True)

    class Meta(PlanTemplateSerializer.Meta):
        fields = PlanTemplateSerializer.Meta.fields + ("rows",)


class FromPlanSerializer(serializers.Serializer):
    """Putting the plan of a course onto the shelf."""

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.none(), required=False, allow_null=True
    )
    grade = serializers.IntegerField(required=False, allow_null=True)
    # «всей школе или только себе» — вопрос того же разговора, что название
    # и описание: на полку кладут ради того, чтобы этим пользовались, и
    # отдельным шагом публикация означала лишь шанс про неё забыть
    is_published = serializers.BooleanField(required=False, default=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        fields["subject"].queryset = school_subjects(self)
        return fields

    def validate(self, attrs):
        course = attrs["course"]
        # Курс отвечает первым, а присланное — только запасной вариант для
        # курсов, заведённых до справочников. Наоборот было нельзя: шаблон
        # снимается **с этого курса**, и «Алгебра 9», уехавшая на полку как
        # «Геометрия 7», расходится с ним молча — форма подставляла значения
        # курса, но ничто не мешало их поправить перед отправкой.
        subject = course.subject or attrs.get("subject")
        # the shelf stores the **year of study**, not the school's name for
        # it: a plan for the ninth year is a plan for the ninth year whether
        # the door says «9Б» or «MYP 4», and one number is what the filter
        # can compare
        grade = course.grade.level if course.grade else attrs.get("grade")

        if subject is None:
            api_error(
                Codes.SUBJECT_REQUIRED,
                "Pick a subject: the library is searched by subject and grade.",
                field="subject",
            )
        if grade is None:
            api_error(
                Codes.GRADE_REQUIRED,
                "Pick a grade: the library is searched by subject and grade.",
                field="grade",
            )

        attrs["subject"] = subject
        attrs["grade"] = grade
        return attrs


class UseTemplateSerializer(serializers.Serializer):
    """
    Taking a template into a course — whole, or by the row.

    `rows` — идентификаторы строк шаблона, которые берут. Нет поля вовсе —
    берут план целиком, как и раньше; курс при этом собирают из готовых
    блоков и отдельных уроков, а не только чужими планами разом.

    Список проверяется здесь, а не в сервисе: строка чужого шаблона так же
    не должна приниматься, как чужой шаблон, — и отказ на неё обязан
    называться, иначе «взял пять уроков, приехало три» осталось бы молчащим.
    """

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    template = serializers.PrimaryKeyRelatedField(
        queryset=PlanTemplate.objects.none()
    )
    mode = serializers.ChoiceField(choices=("replace", "append"), default="replace")
    rows = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=False
    )

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        fields["template"].queryset = visible_templates(
            self.context["request"].user
        )
        return fields

    def validate(self, attrs):
        picked = attrs.get("rows")
        if picked is None:
            return attrs

        known = set(
            attrs["template"].rows.filter(pk__in=picked).values_list("pk", flat=True)
        )
        missing = sorted(set(picked) - known)
        if missing:
            api_error(
                Codes.TEMPLATE_ROW_UNKNOWN,
                "Some of the chosen rows are not in this plan any more. "
                "Open it again and pick them anew.",
                field="rows",
                rows=missing,
            )

        return attrs


class UpdateFromPlanSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        return fields


def visible_templates(user):
    """
    What this person may see: the school's published ones, plus their drafts.

    One definition, used by the viewset and by every field that accepts a
    template id — otherwise a draft nobody may list could still be named in
    a request body.
    """
    from django.db.models import Q

    if user is None or not user.is_authenticated or user.school_id is None:
        return PlanTemplate.objects.none()

    return PlanTemplate.objects.filter(school_id=user.school_id).filter(
        Q(is_published=True) | Q(author=user)
    )
