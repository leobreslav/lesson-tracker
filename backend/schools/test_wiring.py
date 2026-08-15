"""
Every API view is scoped, or is listed here as deliberately not.

The per-model matrix in `test_access.py` proves the rules hold for the models
somebody remembered to write tests for. It cannot prove anything about the
endpoint added next month whose test nobody wrote — and that is the failure
this project is actually exposed to: a new viewset that forgets its base
class answers happily to everyone, and no existing test turns red.

So this walks the URL configuration instead of the models. Every view under
/api/ has to either go through `config.access` or appear in EXEMPT with a
reason. Adding an endpoint therefore forces a decision, in a diff, in front
of a reviewer.
"""

from config.access import (
    CourseScopedViewSet,
    IsStudent,
    IsSuperuser,
    IsTeacher,
    SchoolScopedViewSet,
)
from pathlib import Path

from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver

# Views that are open on purpose, and why. Anything here answers before the
# user is known to belong anywhere, so it must not touch school data.
EXEMPT = {
    "GoogleLoginView": "signing in: there is no user yet",
    "LogoutView": "signing out: only deletes the caller's own token",
    "APIRootView": (
        "DRF's router index: lists the endpoint URLs of a router and no data. "
        "Authenticated like everything else, and every URL it names is itself "
        "scoped — checked by this very test"
    ),
    "MeView": (
        "the caller's own profile, taken from the token, never from a URL — "
        "и ученику она нужна ровно так же, как учителю"
    ),
    "AttachmentViewSet": (
        "вложения нужны обоим видам: учитель читает план и полку, ученик — "
        "сканы своих работ. Вопрос тут «чьё это вложение», а не «кто вы по "
        "виду», и отвечает на него `files.access`: ученику `readable_"
        "attachments` отдаёт только его собственные работы, а `can_write` "
        "не пускает его никуда"
    ),
}

# Права, которые отвечают на вопрос «кому предназначена эта вьюха».
#
# Раньше здесь стоял `IsSchoolMember` и его родня: пока пользователи были
# одни учителя, «состоит в школе» и значило «можно». С появлением учеников
# это перестало быть правдой — членство есть и у них, — поэтому засчитывается
# только явный ответ про вид пользователя.
KIND_AWARE = (IsTeacher, IsStudent, IsSuperuser)


def api_views(prefix="api/"):
    """Every view reachable under /api/, as (route, view class)."""

    def walk(patterns, route=""):
        for entry in patterns:
            here = route + str(entry.pattern)
            if isinstance(entry, URLResolver):
                yield from walk(entry.url_patterns, here)
            elif isinstance(entry, URLPattern):
                view = getattr(entry.callback, "cls", None)
                if view is not None:
                    yield here, view

    seen = {}
    for route, view in walk(get_resolver().url_patterns):
        if route.startswith(prefix):
            seen.setdefault(view.__name__, (route, view))
    return seen


class ApiWiringTests(SimpleTestCase):
    def test_the_walk_finds_the_endpoints(self):
        """A guard for the guard: a broken walk would pass everything."""
        found = api_views()

        self.assertGreater(len(found), 10, found)
        for expected in ("CourseViewSet", "LessonViewSet", "PlanNodeViewSet"):
            self.assertIn(expected, found)

    def test_every_view_answers_whether_a_student_may(self):
        """
        Каждая вьюха отвечает, кому она предназначена, — или объясняет себя.

        Базовые классы несут `IsTeacher` сами, поэтому наследнику ничего
        добавлять не нужно — но проверяется не происхождение, а список прав:
        снятое с базового класса право открыло бы двенадцать вьюсетов разом.
        Забыть здесь значит открыть учительский раздел ученику, и по классу
        вьюхи этого не увидеть — членство в школе у него есть.
        """
        unscoped = []

        for name, (route, view) in sorted(api_views().items()):
            if name in EXEMPT:
                continue
            # базовым классам поблажки нет: право смотрится у самой вьюхи,
            # пусть и унаследованное. Иначе снятое с базового класса
            # `IsTeacher` открыло бы разом двенадцать вьюсетов, а сторож
            # продолжал бы засчитывать их по фамилии предка
            if any(
                issubclass(permission, KIND_AWARE)
                for permission in getattr(view, "permission_classes", [])
            ):
                continue
            unscoped.append(f"{name} ({route})")

        self.assertEqual(
            unscoped,
            [],
            "эти вьюхи не говорят, кому они предназначены: добавьте базовый "
            "класс, IsTeacher/IsSuperuser — или причину в EXEMPT",
        )

    def test_exempt_views_still_exist(self):
        """A stale exemption is a hole that outlives the view it excused."""
        found = api_views()

        self.assertEqual(
            sorted(name for name in EXEMPT if name not in found),
            [],
            "в EXEMPT остались вьюхи, которых больше нет",
        )

    def test_school_scoped_viewsets_declare_a_path_to_the_school(self):
        """
        `school_path` is what the filter walks; a wrong one silently widens it.

        The default "school" is right for models holding the key themselves
        and wrong for anything hanging off a year, so it is checked against
        the model rather than trusted.
        """
        for name, (_, view) in sorted(api_views().items()):
            if not issubclass(view, SchoolScopedViewSet):
                continue

            with self.subTest(name):
                model = view.queryset.model
                complaint = f"{name}.school_path = {view.school_path!r}"

                for step in view.school_path.split("__"):
                    try:
                        field = model._meta.get_field(step)
                    except FieldDoesNotExist:
                        self.fail(f"{complaint}: у {model.__name__} нет поля {step!r}")
                    model = field.related_model
                    self.assertIsNotNone(model, f"{complaint}: {step!r} — не связь")

                self.assertEqual(
                    model.__name__, "School", f"{complaint} ведёт не в School"
                )

    def test_course_scoped_viewsets_point_at_a_course(self):
        """
        `course_path` — такой же путь, как `school_path`: у работы это
        «course», у задачи внутри работы «work__course», у отправки
        «task__work__course». Ошибка в нём молча расширила бы выборку.
        """
        for name, (_, view) in sorted(api_views().items()):
            if not issubclass(view, CourseScopedViewSet):
                continue

            with self.subTest(name):
                model = view.queryset.model
                complaint = f"{name}.course_path = {view.course_path!r}"

                for step in view.course_path.split("__"):
                    try:
                        field = model._meta.get_field(step)
                    except FieldDoesNotExist:
                        self.fail(f"{complaint}: у {model.__name__} нет поля {step!r}")
                    model = field.related_model
                    self.assertIsNotNone(model, f"{complaint}: {step!r} — не связь")

                self.assertEqual(
                    model.__name__, "Course", f"{complaint} ведёт не в Course"
                )


# Действия, у которых нет объекта на входе: спрашивать «а отличается ли
# ответ на чужой id» тут не о чем. Причина у каждого своя, и она нужна:
# ошибиться легко именно здесь, приписав сюда действие с id в теле.
ACTIONS_WITHOUT_ID = {
    "lesson-agenda": "период и только он: своё расписание за даты",
    "lesson-summary": "сводка по расписанию школы, id на входе нет",
    "plannode-layout-agenda": "то же самое, темы уроков за период",
    "plannode-progress": "все свои курсы разом, id на входе нет",
    "gradelevel-preset": "«завести 1..N», на вход одно число",
    "gradelevel-delete-unused": "убрать все параллели без курсов",
}


class ActionCoverageTests(SimpleTestCase):
    """
    Сторож для матрицы: каждое действие должно быть в ней перечислено.

    `test_wiring` выше следит за классами вьюх, но действие внутри класса
    ходит в модели своим кодом — фильтрует руками или не фильтрует вовсе, а
    класс при этом на месте и права объявлены. Матрица такие действия
    проверяет (`assertActionRules`), но список в ней ручной, и новое
    действие в него никто не обязан добавлять.

    Поэтому список сверяется с роутером: появилось действие — либо оно
    названо в `test_access.py`, либо записано сюда с причиной.
    """

    STANDARD = {
        "list",
        "create",
        "retrieve",
        "update",
        "partial_update",
        "destroy",
    }

    def extra_actions(self):
        """Имена маршрутов всех `@action` под /api/."""
        found = {}

        def walk(patterns, route=""):
            for entry in patterns:
                here = route + str(entry.pattern)
                if isinstance(entry, URLResolver):
                    walk(entry.url_patterns, here)
                    continue

                actions = getattr(entry.callback, "actions", None)
                if not here.startswith("api/") or not actions:
                    continue
                if set(actions.values()) - self.STANDARD:
                    found[entry.name] = here

        walk(get_resolver().url_patterns)
        return found

    def test_every_action_is_in_the_matrix_or_excused(self):
        source = (
            Path(__file__).resolve().parent / "test_access.py"
        ).read_text(encoding="utf-8")

        found = self.extra_actions()
        self.assertGreater(len(found), 20, f"обход сломался: {found}")

        missing = sorted(
            name
            for name in found
            if name not in ACTIONS_WITHOUT_ID and f'"{name}"' not in source
        )

        self.assertEqual(
            missing,
            [],
            "эти действия не проверены матрицей: добавьте их в actions= "
            "нужной модели или в ACTIONS_WITHOUT_ID с причиной",
        )

    def test_the_excuses_still_point_at_something(self):
        found = self.extra_actions()

        self.assertEqual(
            sorted(name for name in ACTIONS_WITHOUT_ID if name not in found),
            [],
            "в ACTIONS_WITHOUT_ID остались действия, которых больше нет",
        )
