"""Работы и задачи в JSON. Ответы ученика — отдельно, у них другой читатель."""

from config.errors import Codes, api_error
from rest_framework import serializers
from schedule.models import Course

import json

from django.contrib.auth import get_user_model

from .models import MAX_CRITERIA, MAX_MARK, MAX_SCAN_BYTES, Submission, Task, Work

User = get_user_model()


def teacher_courses(serializer):
    """Курсы, в которых спрашивающий вообще может что-то заводить."""
    user = getattr(serializer.context.get("request"), "user", None)
    return Course.objects.for_teacher(user)


class TaskSerializer(serializers.ModelSerializer):
    """
    Задача глазами учителя: условие, эталоны и цена правки.

    `impact` не считается для списка — там он был бы запросом на строку, а
    показывают его в одном месте: когда задачу открывают на правку.
    """

    # свой список, а не тот, что DRF выводит из ArrayField: тот отвергает
    # пустую строку раньше, чем до неё дойдёт очередь, и `trim_whitespace`
    # у него включён — а эталон, как и ответ, хранится ровно как введён
    answers = serializers.ListField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        required=False,
    )

    class Meta:
        model = Task
        fields = ("id", "work", "position", "question", "answers", "created_at")
        read_only_fields = ("id", "position", "created_at")

    def validate_question(self, value):
        if not value.strip():
            api_error(
                Codes.TASK_QUESTION_REQUIRED,
                "A task needs a question.",
                field="question",
            )
        return value

    def validate_answers(self, value):
        # пустые строки в списке эталонов — след пустой строки формы, а не
        # ответ «ничего»: пустой ответ выражается пустым списком
        return [answer for answer in value if answer.strip()]

    def get_fields(self):
        fields = super().get_fields()
        fields["work"].queryset = Work.objects.filter(
            course__in=teacher_courses(self)
        )
        return fields


class WorkSerializer(serializers.ModelSerializer):
    """
    Работа глазами учителя.

    `state` отдаётся сервером, а не считается на клиенте: «открыта ли» —
    вопрос о времени, и два ответа на него (у браузера часы свои) означали
    бы работу, которая на экране открыта, а на сервере ещё нет.
    """

    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())
    course_name = serializers.CharField(source="course.name", read_only=True)
    state = serializers.SerializerMethodField()
    tasks_count = serializers.SerializerMethodField()

    class Meta:
        model = Work
        fields = (
            "id",
            "course",
            "course_name",
            "created_by",
            "title",
            "description",
            "opens_at",
            "closes_at",
            "attempts",
            "show_result",
            "on_paper",
            "is_homework",
            "slot",
            "state",
            "tasks_count",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def get_state(self, work) -> str:
        return work.state()

    def get_tasks_count(self, work) -> int:
        # аннотация вьюсета; у только что созданной работы задач ноль, и это
        # правда, а не отсутствие данных
        return getattr(work, "task_count", 0)

    def validate(self, attrs):
        def value(name):
            return attrs.get(name, getattr(self.instance, name, None))

        if value("closes_at") <= value("opens_at"):
            api_error(
                Codes.WORK_DATES_REVERSED,
                "The work closes before it opens.",
                field="closes_at",
            )

        return attrs

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        # занятие — из своих курсов; поле необязательное
        from schedule.models import Slot

        fields["slot"].queryset = Slot.objects.filter(
            course__in=fields["course"].queryset
        )
        return fields


class SubmissionSerializer(serializers.ModelSerializer):
    """
    Отправка глазами учителя: ответ, время и отметка.

    Из полей меняется одно — `is_correct`. Ответ ученика не правится ни при
    каких обстоятельствах: это его слова, а не наша запись о них.
    """

    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = (
            "id",
            "task",
            "student",
            "student_name",
            "answer",
            "created_at",
            "is_correct",
            "checked_at",
        )
        read_only_fields = (
            "id",
            "task",
            "student",
            "answer",
            "created_at",
            "checked_at",
        )

    def get_student_name(self, submission) -> str:
        from . import services

        return services.full_name(submission.student)


# --- то же самое, но для ученика --------------------------------------------------


class StudentSubmissionSerializer(serializers.ModelSerializer):
    """Одна отправка в истории ученика. Вердикт может быть скрыт настройкой."""

    verdict = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ("id", "answer", "created_at", "verdict")

    def get_verdict(self, submission):
        from . import services

        return services.verdict_for(self.context["work"], submission)


class CriterionSerializer(serializers.Serializer):
    """Одна строка шкалы. Имя пустое — обычная отметка, а не критерий."""

    name = serializers.CharField(max_length=100, allow_blank=True, default="")
    maximum = serializers.IntegerField(min_value=1, max_value=MAX_MARK)


class CriteriaSerializer(serializers.Serializer):
    """
    Шкала целиком. Пустой список законен: работа не оценивается.

    Порядок берётся из списка — позиция это индекс, и другого источника у
    неё нет. Тот же приём, что у строк шаблона в библиотеке, и по той же
    причине: построчный CRUD потребовал бы своей перенумерации ради формы,
    у которой вложенности нет.
    """

    criteria = CriterionSerializer(many=True)

    def validate_criteria(self, value):
        if len(value) > MAX_CRITERIA:
            api_error(
                Codes.TOO_MANY_CRITERIA,
                f"A work is graded by at most {MAX_CRITERIA} criteria.",
                field="criteria",
                limit=MAX_CRITERIA,
            )
        return value


class GradeSerializer(serializers.Serializer):
    """
    Оценка одного ученика: набор «критерий → значение» плюс комментарий.

    Значение `null` снимает отметку — тем же движением, что и вердикт у
    отправки. Критерий чужой работы не примем: перепутать их легко, а
    последствие — оценка, поставленная не туда.
    """

    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    marks = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=MAX_MARK, allow_null=True),
        required=False,
    )
    comment = serializers.CharField(required=False, allow_blank=True)

    def get_fields(self):
        fields = super().get_fields()
        work = self.context["work"]
        # только ученики этого курса, включая снятых: работа у них была, и
        # оценка за неё тоже
        fields["student"].queryset = User.objects.filter(
            enrolments__course_id=work.course_id
        )
        return fields

    def validate(self, attrs):
        work = self.context["work"]
        scale = {item.pk: item for item in work.criteria.all()}

        raw = attrs.get("marks") or {}
        marks = {}
        for key, value in raw.items():
            criterion = scale.get(int(key)) if str(key).isdigit() else None
            if criterion is None:
                api_error(
                    Codes.CRITERION_UNKNOWN,
                    "That criterion does not belong to this work.",
                    field="marks",
                )
            if value is not None and value > criterion.maximum:
                api_error(
                    Codes.MARK_OUT_OF_RANGE,
                    f"«{criterion.name or criterion.maximum}»: the mark is above "
                    f"the maximum of {criterion.maximum}.",
                    field="marks",
                    maximum=criterion.maximum,
                )
            marks[criterion.pk] = value

        attrs["marks"] = marks
        return attrs


class PieceSerializer(serializers.Serializer):
    """Один кусок разметки: чья работа и с какой по какую страницу."""

    student = serializers.IntegerField()
    first = serializers.IntegerField(min_value=1)
    last = serializers.IntegerField(min_value=1)


class SplitSerializer(serializers.Serializer):
    """
    Скан и разметка к нему.

    Разметка приезжает строкой JSON, потому что файл идёт multipart'ом, и
    вложенные структуры в такой форме не выражаются. Это единственная
    причина; списком объектов она и остаётся.
    """

    file = serializers.FileField()
    plan = serializers.CharField()

    def validate(self, attrs):
        from . import splitting

        upload = attrs["file"]
        if upload.size > MAX_SCAN_BYTES:
            api_error(
                Codes.FILE_TOO_LARGE,
                f"The scan is larger than {MAX_SCAN_BYTES // 1024 // 1024} MB.",
                field="file",
                limit_mb=MAX_SCAN_BYTES // 1024 // 1024,
            )

        data = upload.read()
        try:
            pages = splitting.read_pages(data)
        except splitting.SplitError as error:
            api_error(Codes.FILE_NOT_PDF, str(error), field="file")

        try:
            rows = json.loads(attrs["plan"])
        except ValueError:
            api_error(Codes.SPLIT_EMPTY, "The markup is not readable.", field="plan")

        form = PieceSerializer(data=rows, many=True)
        form.is_valid(raise_exception=True)
        pieces = [
            splitting.Piece(
                student_id=item["student"], first=item["first"], last=item["last"]
            )
            for item in form.validated_data
        ]

        work = self.context["work"]
        students = set(
            work.course.students.values_list("student_id", flat=True)
        )
        splitting.check_plan(pieces, pages=pages, students=students)

        attrs["data"] = data
        attrs["plan"] = pieces
        return attrs


class ReassignSerializer(serializers.Serializer):
    """Переложить приложенную работу другому ученику того же курса."""

    attachment = serializers.IntegerField()
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        work = self.context["work"]
        fields["student"].queryset = User.objects.filter(
            enrolments__course_id=work.course_id
        )
        return fields

    def validate_attachment(self, value):
        from files.models import Attachment

        work = self.context["work"]
        found = Attachment.objects.filter(
            pk=value, student_work__work=work
        ).first()
        if found is None:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That attachment does not belong to this work.",
                field="attachment",
            )
        return found
