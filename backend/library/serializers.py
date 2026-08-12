from config.errors import Codes, api_error
from rest_framework import serializers
from schedule.models import Course, Subject
from schedule.serializers import school_courses

from .models import PlanTemplate, PlanTemplateRow


def school_subjects(serializer):
    """Subjects of the requester's school — another school's are invisible."""
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return Subject.objects.none()
    return Subject.objects.filter(school_id=user.school_id)


class TemplateRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanTemplateRow
        fields = ("id", "position", "is_header", "title", "note")
        read_only_fields = ("id", "position")


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

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        fields["subject"].queryset = school_subjects(self)
        return fields

    def validate(self, attrs):
        course = attrs["course"]
        # the course usually knows both already; the form only asks when it
        # does not, which is the case for courses made before subjects existed
        subject = attrs.get("subject") or course.subject
        grade = attrs.get("grade") or course.grade

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
    """Taking a template into a course."""

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    template = serializers.PrimaryKeyRelatedField(
        queryset=PlanTemplate.objects.none()
    )
    mode = serializers.ChoiceField(choices=("replace", "append"), default="replace")

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        fields["template"].queryset = visible_templates(
            self.context["request"].user
        )
        return fields


class UpdateFromPlanSerializer(serializers.Serializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
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
