from calendars import services as calendar_services
from calendars.serializers import CurrentSchoolDefault, school_years
from config.errors import Codes, api_error, error_payload
from calendars.models import SchoolYear
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from . import services
from .models import Course, LessonSlot, MasterSlot, Subject

User = get_user_model()


def school_members(serializer):
    """People of the requester's school — the only ones a lesson can name."""
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return User.objects.none()
    return User.objects.filter(school_id=user.school_id)


def school_courses(serializer):
    """
    Courses of the requester's school — another school's cannot be referenced.

    A foreign key in the body bypasses the viewset's filter, so the choices
    are narrowed here as well.
    """
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated or user.school_id is None:
        return Course.objects.none()
    return Course.objects.filter(school_id=user.school_id)


class SubjectSerializer(serializers.ModelSerializer):
    """A subject of the school. Administrators keep the list."""

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    courses = serializers.IntegerField(source="courses.count", read_only=True)

    class Meta:
        model = Subject
        fields = ("id", "school", "name", "courses")
        validators = [
            UniqueTogetherValidator(
                queryset=Subject.objects.all(),
                fields=("school", "name"),
                message="This school already has a subject with that name.",
            ),
        ]


class CourseSerializer(serializers.ModelSerializer):
    # the school comes from the requester, never from the body
    school = serializers.HiddenField(default=CurrentSchoolDefault())
    subject_name = serializers.CharField(source="subject.name", read_only=True)

    class Meta:
        model = Course
        fields = (
            "id",
            "school",
            "year",
            "subject",
            "subject_name",
            "grade",
            "name",
            "created_at",
        )
        read_only_fields = ("created_at",)
        validators = [
            # school is not in the request body, so DRF cannot check
            # unique_together on its own — a duplicate would give a 500
            UniqueTogetherValidator(
                queryset=Course.objects.all(),
                fields=("school", "year", "name"),
                message="A course with this name already exists in this year.",
            ),
        ]

    def get_fields(self):
        fields = super().get_fields()
        # a course can only live in a year of its own school
        fields["year"].queryset = school_years(self)
        fields["subject"].queryset = Subject.objects.filter(
            school_id=getattr(self.context.get("request").user, "school_id", None)
        )
        return fields


class LessonSlotSerializer(serializers.ModelSerializer):
    # the teacher comes from the token: the body cannot name somebody else,
    # and unique_together needs the field to exist on the serializer
    teacher = serializers.HiddenField(default=serializers.CurrentUserDefault())
    # the year follows from the course and need not be sent
    year = serializers.PrimaryKeyRelatedField(
        queryset=SchoolYear.objects.none(), required=False
    )
    warning = serializers.SerializerMethodField()

    class Meta:
        model = LessonSlot
        fields = (
            "id",
            "teacher",
            "year",
            "course",
            "date",
            "lesson_number",
            "is_cancelled",
            "is_extra",
            "reason",
            "created_at",
            "warning",
        )
        read_only_fields = ("created_at",)
        validators = [
            # teacher is not in the body either — it comes from the token
            UniqueTogetherValidator(
                queryset=LessonSlot.objects.all(),
                fields=("teacher", "course", "date", "lesson_number"),
                message="You already have a lesson with this number in this course that day.",
            ),
        ]

    def get_fields(self):
        fields = super().get_fields()
        courses = school_courses(self)
        fields["course"].queryset = courses
        fields["year"].queryset = SchoolYear.objects.filter(
            pk__in=courses.values("year_id")
        )
        return fields

    def get_warning(self, obj):
        """
        A lesson on a non-study day is allowed — catch-up days happen — but
        the answer says so, coded like an error so the UI can localise it.
        """
        day = calendar_services.resolve_day(
            obj.date, obj.year.weekend_days, obj.year.periods()
        )
        if day.is_study:
            return None

        label = calendar_services.STATUS_LABELS[day.status]
        note = f" «{day.title}»" if day.title else ""
        return error_payload(
            Codes.SLOT_NOT_STUDY_DAY,
            f"{obj.date.isoformat()} is a {label}{note}: the lesson falls outside study days.",
            date=obj.date.isoformat(),
            status=day.status,
            title=day.title,
        )

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        course = value("course")
        year = attrs.get("year") or course.year
        slot_date = value("date")

        if year != course.year:
            api_error(
                Codes.SLOT_YEAR_MISMATCH,
                "The lesson year must match the year of its course.",
                field="year",
            )

        if not year.start_date <= slot_date <= year.end_date:
            api_error(
                Codes.SLOT_OUTSIDE_YEAR,
                "The date is outside the school year "
                f"({year.start_date} — {year.end_date}).",
                field="date",
                start=str(year.start_date),
                end=str(year.end_date),
            )

        if not value("is_cancelled"):
            # one teacher cannot run two courses on the same number
            busy = LessonSlot.find_conflict(
                teacher_id=self.context["request"].user.pk,
                year=year,
                date=slot_date,
                lesson_number=value("lesson_number"),
                exclude_pk=self.instance.pk if self.instance else None,
            )
            if busy is not None:
                api_error(
                    Codes.SLOT_NUMBER_TAKEN,
                    services.occupied_message(
                        slot_date, value("lesson_number"), busy.course.name
                    ),
                    field="lesson_number",
                    date=str(slot_date),
                    number=value("lesson_number"),
                    class_name=busy.course.name,
                )

        attrs["year"] = year
        return attrs


class MasterSlotSerializer(serializers.ModelSerializer):
    """A row of the school timetable. The school comes from the requester."""

    school = serializers.HiddenField(default=CurrentSchoolDefault())
    course_name = serializers.CharField(source="course.name", read_only=True)
    teacher_name = serializers.SerializerMethodField()

    class Meta:
        model = MasterSlot
        fields = (
            "id",
            "school",
            "year",
            "course",
            "course_name",
            "teacher",
            "teacher_name",
            "date",
            "lesson_number",
        )
        validators = [
            UniqueTogetherValidator(
                queryset=MasterSlot.objects.all(),
                fields=("course", "date", "lesson_number"),
                message="This course already has a lesson with this number that day.",
            ),
        ]

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        fields["year"].queryset = school_years(self)
        fields["teacher"].queryset = school_members(self)
        return fields

    def get_teacher_name(self, obj):
        if obj.teacher is None:
            return None
        full = f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        return full or obj.teacher.email

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        course = value("course")
        year = value("year") or course.year
        teacher = value("teacher")
        day = value("date")
        number = value("lesson_number")

        if year != course.year:
            api_error(
                Codes.SLOT_YEAR_MISMATCH,
                "The lesson year must match the year of its course.",
                field="year",
            )

        if not year.start_date <= day <= year.end_date:
            api_error(
                Codes.SLOT_OUTSIDE_YEAR,
                f"The date is outside the school year "
                f"({year.start_date} — {year.end_date}).",
                field="date",
                start=str(year.start_date),
                end=str(year.end_date),
            )

        # a row with no teacher yet cannot clash with anybody
        busy = MasterSlot.find_conflict(
            teacher_id=teacher.pk if teacher else None,
            date=day,
            lesson_number=number,
            exclude_pk=self.instance.pk if self.instance else None,
        )
        if busy is not None:
            api_error(
                Codes.SLOT_NUMBER_TAKEN,
                services.occupied_message(day, number, busy.course.name),
                field="lesson_number",
                date=str(day),
                number=number,
                class_name=busy.course.name,
            )

        attrs["year"] = year
        return attrs


class ImportFromSchoolSerializer(serializers.Serializer):
    """
    What a teacher asks to be copied out of the school timetable.

    `courses` left out means every course they are down for — the usual
    request, and the one the interface sends by default.
    """

    year = serializers.PrimaryKeyRelatedField(queryset=SchoolYear.objects.none())
    # a ListField rather than many=True: DRF does not pass allow_null down to
    # the wrapper it builds, and the interface sends an explicit null for
    # «every course of mine»
    courses = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Course.objects.none()),
        required=False,
        allow_null=True,
    )
    start = serializers.DateField()
    end = serializers.DateField()
    mode = serializers.ChoiceField(choices=("replace", "merge"), default="merge")

    def get_fields(self):
        fields = super().get_fields()
        fields["year"].queryset = school_years(self)
        fields["courses"].child.queryset = school_courses(self)
        return fields

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs


class CopySerializer(serializers.Serializer):
    """
    Input for /api/slots/copy/.

    Without `course_id` the whole schedule is copied — every course this
    teacher works in whose year touches the target period.
    """

    course_id = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.none(),
        source="course",
        required=False,
        allow_null=True,
    )
    source_start = serializers.DateField()
    source_end = serializers.DateField()
    target_start = serializers.DateField()
    target_end = serializers.DateField()
    mode = serializers.ChoiceField(choices=("replace", "merge"), default="merge")

    def get_fields(self):
        fields = super().get_fields()
        fields["course_id"].queryset = school_courses(self)
        return fields

    def validate(self, attrs):
        for start, end in (("source_start", "source_end"), ("target_start", "target_end")):
            if attrs[end] < attrs[start]:
                api_error(
                    Codes.PERIOD_REVERSED,
                    "The end date is earlier than the start date.",
                    field=end,
                )
        return attrs


class PeriodSerializer(serializers.Serializer):
    """Period boundaries for /api/slots/agenda/."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs


class BulkDeleteSerializer(serializers.Serializer):
    """Input for DELETE /api/slots/bulk/ — it arrives as query parameters."""

    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.none())
    start = serializers.DateField()
    end = serializers.DateField()
    only_regular = serializers.BooleanField(default=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = school_courses(self)
        return fields

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            api_error(
                Codes.PERIOD_REVERSED,
                "The end date is earlier than the start date.",
                field="end",
            )
        return attrs
