"""
Две половины одного экрана: учитель составляет работу, ученик её решает.

Учительская половина — объект курса (`CourseScopedViewSet`), как и учебный
план; у ученической свои вьюхи: спрашивают они другое и отвечают другим, а
общий вьюсет с ветками «если ученик» был бы длиннее двух.
"""

from config.access import (
    CourseScopedViewSet,
    IsSchoolMember,
    IsStudent,
    IsTeacher,
)
from config.errors import Codes, api_error
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Submission, Task, Work
from .serializers import (
    StudentSubmissionSerializer,
    SubmissionSerializer,
    TaskSerializer,
    WorkSerializer,
)


class WorkViewSet(CourseScopedViewSet):
    """
    Работы курса. Принадлежат курсу, как и план: читает тот, кто в курсе
    работает, правит назначенный ведущий.

    Правку открытой работы никто не запрещает — она отвечает `impact`, и
    интерфейс называет цену числом: «сейчас решают семнадцать человек».
    Запрет здесь дороже ошибки: опечатку в условии находят посреди урока.
    """

    serializer_class = WorkSerializer
    queryset = Work.objects.select_related("course")
    course_path = "course"

    def get_queryset(self):
        queryset = super().get_queryset().annotate(task_count=Count("tasks"))

        course = self.request.query_params.get("course")
        if course:
            queryset = (
                queryset.filter(course_id=course)
                if course.isdigit()
                else queryset.none()
            )

        return queryset

    def perform_destroy(self, instance):
        """
        Удаление уносит задачи и ответы: это каскад, и он намеренный.

        Ответы живут внутри работы и вне её не значат ничего — «ответ на
        задачу, которой нет» нельзя ни прочитать, ни оценить. Поэтому цена
        названа заранее: `impact` показывает, сколько ответов исчезнет, и
        интерфейс спрашивает подтверждение.
        """
        instance.delete()

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        """Что стоит за этой работой прямо сейчас — до того, как её правят."""
        work = self.get_object()

        return Response(services.impact_of(work))

    @action(detail=True, methods=["get"])
    def table(self, request, pk=None):
        """
        Сводная таблица: ученики по строкам, задачи по столбцам.

        `?version=` делает опрос дешёвым. Экран спрашивает раз в несколько
        секунд, воркеров у прода два, и ответ «ничего не изменилось» обязан
        стоить один агрегат, а не сборку трёхсот ячеек. Совпала версия —
        отвечаем `changed: false` и больше ничем.
        """
        work = self.get_object()
        version = services.table_version(work)

        if request.query_params.get("version") == version:
            return Response({"version": version, "changed": False})

        return Response(services.build_table(work))


class TaskViewSet(CourseScopedViewSet):
    """
    Задачи внутри работы. Курс тот же, путь до него — через работу.

    Позиции плотные, как в плане: новая встаёт в конец, `move` двигает на
    шаг, удаление перенумеровывает уровень.
    """

    serializer_class = TaskSerializer
    queryset = Task.objects.select_related("work")
    course_path = "work__course"

    def get_queryset(self):
        queryset = super().get_queryset()

        work = self.request.query_params.get("work")
        if work:
            queryset = (
                queryset.filter(work_id=work) if work.isdigit() else queryset.none()
            )

        return queryset

    def perform_create(self, serializer):
        work = serializer.validated_data["work"]
        self.require_lead(work.course)
        serializer.save(position=services.next_position(work))

    def perform_destroy(self, instance):
        work = instance.work
        instance.delete()
        services.reindex(work)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """`{"direction": "up"|"down"}`; `{"moved": false}` — край, не ошибка."""
        task = self.get_object()
        direction = request.data.get("direction")
        if direction not in ("up", "down"):
            api_error(
                Codes.MODE_INVALID,
                "Direction must be «up» or «down».",
                field="direction",
            )

        return Response({"moved": services.move(task, direction)})

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        """Сколько ответов и вердиктов затронет правка этой задачи."""
        return Response(services.task_impact(self.get_object()))

    @action(detail=True, methods=["post"])
    def recheck(self, request, pk=None):
        """
        Снять отметки со всех отправок задачи.

        Главный случай — неверный эталон: половина класса проверена
        неправильно, и вердикты надо вернуть в «не проверено», не трогая
        сами ответы.
        """
        return Response({"reset": services.reset_verdicts(self.get_object())})


class SubmissionViewSet(CourseScopedViewSet):
    """
    Отправки учеников: читать и отмечать. Больше ничего.

    Ни создать, ни удалить: журнал пишет ученик, и строка в нём — событие,
    а не запись, которую правят. Учителю принадлежит **отметка**, и она
    здесь единственное изменяемое поле.

    Проверяют чаще по задачам, чем по ученикам: открыть столбец и пройти
    все ответы подряд — глаз настроен на один эталон. Поэтому список
    сужается и по задаче, и по ученику, а ячейка таблицы — это тот же
    список из одной пары.
    """

    serializer_class = SubmissionSerializer
    queryset = Submission.objects.select_related("student", "task")
    course_path = "task__work__course"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()

        for param, lookup in (
            ("task", "task_id"),
            ("student", "student_id"),
            ("work", "task__work_id"),
        ):
            raw = self.request.query_params.get(param)
            if raw:
                queryset = (
                    queryset.filter(**{lookup: raw})
                    if raw.isdigit()
                    else queryset.none()
                )

        return queryset.order_by("created_at", "id")

    def perform_update(self, serializer):
        """
        Отметка ставится и снимается одним и тем же PATCH.

        `null` — «снять»: учитель передумал или увидел, что смотрел не ту
        отправку. Попытку это не расходует и журнал не трогает: отметка
        живёт на строке, а строка неизменна.
        """
        checked = serializer.validated_data.get("is_correct") is not None
        serializer.save(
            checked_at=timezone.now() if checked else None,
            checked_by=self.request.user if checked else None,
        )


# --- половина ученика --------------------------------------------------------------


class StudentWorksView(APIView):
    """
    Работы ученика: открытые, закрытые и его продвижение по ним.

    Ненаступивших здесь нет вовсе — «черновика» у работы нет, и до открытия
    окна её не существует. Закрытые остаются: ответы и отметки читать можно
    всегда.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def get(self, request):
        works = list(services.visible_works(request.user))
        totals = services.totals_for(works, student=request.user)
        active = set(
            request.user.enrolments.filter(removed_at__isnull=True).values_list(
                "course_id", flat=True
            )
        )

        return Response(
            {
                "works": [
                    {
                        "id": work.pk,
                        "title": work.title,
                        "course_id": work.course_id,
                        "course_name": work.course.name,
                        "state": work.state(),
                        "opens_at": work.opens_at,
                        "closes_at": work.closes_at,
                        # снятый с курса видит работу и свои ответы, но
                        # решать в ней больше не может
                        "can_answer": work.state() == "open"
                        and work.course_id in active,
                        "tasks": totals[work.pk]["tasks"],
                        "answered": totals[work.pk]["answered_tasks"],
                    }
                    for work in works
                ]
            }
        )


class StudentWorkView(APIView):
    """Одна работа целиком: задачи, свои ответы и что ещё можно отправить."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def get(self, request, pk):
        work = get_object_or_404(services.visible_works(request.user), pk=pk)

        # опрос у ученика такой же, как у учителя, и по той же причине:
        # отметка приходит к нему без его участия, а страница, которую
        # приходится обновлять руками, — это страница, которой не верят
        version = services.student_version(work, request.user)
        if request.query_params.get("version") == version:
            return Response({"version": version, "changed": False})

        tasks = list(work.tasks.all())
        journal = services.my_answers(request.user, tasks)
        active = request.user.enrolments.filter(
            course_id=work.course_id, removed_at__isnull=True
        ).exists()

        return Response(
            {
                "version": version,
                "id": work.pk,
                "title": work.title,
                "course_name": work.course.name,
                "state": work.state(),
                "opens_at": work.opens_at,
                "closes_at": work.closes_at,
                "attempts": work.attempts,
                "can_answer": work.state() == "open" and active,
                "tasks": [
                    {
                        "id": task.pk,
                        "position": task.position,
                        "question": task.question,
                        "attempts_left": services.attempts_left(
                            work, len(journal[task.pk])
                        ),
                        "submissions": StudentSubmissionSerializer(
                            journal[task.pk], many=True, context={"work": work}
                        ).data,
                    }
                    for task in tasks
                ],
            }
        )


class StudentAnswerView(APIView):
    """
    Отправка ответа: одна задача, одна попытка, новая строка журнала.

    Ответы уходят по одной задаче, а не всё разом в конце: браузер закроют,
    интернет отвалится, урок кончится — и работа, отправляемая целиком, в
    этот момент теряется вся.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsStudent]

    def post(self, request, pk):
        task = get_object_or_404(
            Task.objects.filter(
                work__in=services.visible_works(request.user)
            ).select_related("work"),
            pk=pk,
        )
        text = request.data.get("answer")
        if not isinstance(text, str):
            api_error(Codes.TASK_QUESTION_REQUIRED, "An answer is required.", field="answer")

        submission = services.answer(task, request.user, text)
        used = Submission.objects.filter(task=task, student=request.user).count()

        return Response(
            {
                "submission": StudentSubmissionSerializer(
                    submission, context={"work": task.work}
                ).data,
                "attempts_left": services.attempts_left(task.work, used),
            },
            status=status.HTTP_201_CREATED,
        )
