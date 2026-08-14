"""Работы и задачи в JSON. Ответы ученика — отдельно, у них другой читатель."""

from config.errors import Codes, api_error
from rest_framework import serializers
from schedule.models import Course

from .models import Submission, Task, Work


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
            "opens_at",
            "closes_at",
            "attempts",
            "show_result",
            "lesson",
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
        # урок плана — из планов своих курсов; поле необязательное
        from plans.models import PlanNode

        fields["lesson"].queryset = PlanNode.objects.filter(
            course__in=fields["course"].queryset, is_section=False
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
