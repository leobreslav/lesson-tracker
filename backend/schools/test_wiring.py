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
    IsFamily,
    IsParent,
    IsParentOrTeacher,
    IsStudent,
    IsSuperuser,
    IsTeacher,
    SchoolScopedViewSet,
)
from io import StringIO
from pathlib import Path

from django.core.exceptions import FieldDoesNotExist
from django.core.management import call_command
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
    "TaskThreadView": (
        "разговор о задаче нужен обеим сторонам: ученик спрашивает, учитель "
        "отвечает, и оба ходят по одному адресу. Вопрос тут «твой ли это "
        "тред», а не «кто ты по виду», и отвечает на него `works.threads`: "
        "ученику виден только свой, учителю — треды курсов, которые он ведёт"
    ),
    "StudentTrackView": (
        "след ученика нужен обеим сторонам: ученик смотрит свой, учитель — "
        "своих учеников по своим курсам. Вопрос тут «чей это след», а не «кто "
        "вы по виду», и отвечает на него сама вьюха: ученику отдаётся только "
        "его собственный (чужой — 404), учителю — сужённый его курсами"
    ),
    "AttachmentViewSet": (
        "вложения нужны обоим видам: учитель читает план и полку, ученик — "
        "сканы своих работ. Вопрос тут «чьё это вложение», а не «кто вы по "
        "виду», и отвечает на него `files.access`: ученику `readable_"
        "attachments` отдаёт только его собственные работы, а `can_write` "
        "не пускает его никуда"
    ),
    "ContentImageView": (
        "картинка, стоящая в тексте, нужна обеим сторонам: содержание урока "
        "читает учитель, пояснения к работе — весь класс, а картинка в них "
        "часть условия. Вопрос тут «есть ли у вас своя читаемая ссылка на "
        "этот файл» (`files.access.readable_stored_file`), а не «кто вы по "
        "виду»: ученику своими оказываются только открытые ему работы и его "
        "собственная тетрадь"
    ),
    "PhotoMarkupView": (
        "просмотрщик один на обе стороны, и это его смысл: учитель обводит "
        "ошибку, ученик её видит. Разведи на две вьюхи — и они разойдутся, "
        "а узнает об этом ученик. Вопрос тут «чей это снимок» (`files."
        "access.can_read`), а «кому можно рисовать» отвечает `works.photos."
        "may_draw`: поворот и пометки пишет только ведущий курса"
    ),
    "PhotoStrokesView": (
        "перо на том же снимке: читать его нужно обеим сторонам, а рисовать "
        "— только учителю. Право по объекту (`works.photos.may_draw`), а не "
        "по виду: учитель чужого курса сюда не проходит так же, как ученик"
    ),
    "PhotoNotesView": (
        "приколоть заметку к месту на снимке — то же право, что у пера "
        "(`works.photos.may_draw`); стоит рядом с ним и по тому же доводу"
    ),
    "TalksView": (
        "переписка нужна всем трём видам, и это её смысл: собеседник не меняет "
        "природы разговора. Вопрос тут «с кем **вы** говорили», а не «кто вы по "
        "виду», и отвечает на него `talks.access`: собеседники считаются от "
        "спрашивающего — коллеги учителю, ведущие своих курсов семье"
    ),
    "TalkView": (
        "тот же разговор с одним человеком. Право по участию (`talks.access."
        "may_write_to`), а не по виду: чужая переписка не читается никем, "
        "включая администратора школы, а собеседник из другой школы не "
        "существует вовсе"
    ),
    "PhotoNoteView": (
        "разговор о месте на снимке нужен обеим сторонам, как и разговор о "
        "задаче: учитель говорит «здесь потерян минус», ученик спрашивает "
        "почему. Право по участию (`works.photos.may_say` поверх `can_"
        "read`), а убрать заметку может только тот, кто размечает"
    ),
}

# Права, которые отвечают на вопрос «кому предназначена эта вьюха».
#
# Раньше здесь стоял `IsSchoolMember` и его родня: пока пользователи были
# одни учителя, «состоит в школе» и значило «можно». С появлением учеников
# это перестало быть правдой — членство есть и у них, — поэтому засчитывается
# только явный ответ про вид пользователя.
#
# Родитель добавил в список три ответа, и все три именно ответы, а не
# послабления: `IsFamily` — «ученическое, и родителю про ребёнка тоже»,
# `IsParent` — «только родителю», `IsParentOrTeacher` — «две стороны
# разговора о ребёнке». Чей именно ребёнок, решает не право, а
# `families.viewing.subject_of`; право отвечает только на «кому раздел».
KIND_AWARE = (
    IsTeacher,
    IsStudent,
    IsFamily,
    IsParent,
    IsParentOrTeacher,
    IsSuperuser,
)


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
        for expected in ("CourseViewSet", "SlotViewSet", "PlanNodeViewSet"):
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
    "slot-agenda": "период и только он: своё расписание за даты",
    "slot-summary": "сводка по расписанию школы, id на входе нет",
    "slot-unclosed": "долги по своим курсам: на входе ничего",
    "slot-close": "закрытие пачкой: список в теле, id на входе нет",
    "slot-repeat": "ряд уроков: курс и дата в теле, id на входе нет",
    "plannode-layout-agenda": "то же самое, темы уроков за период",
    "gradelevel-preset": "«завести 1..N», на вход одно число",
    "gradelevel-delete-unused": "убрать все параллели без курсов",
    "work-from-bank": "сборка из банка: курс в теле, работы ещё нет",
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


class MigrationTests(SimpleTestCase):
    """
    Модель изменили — миграция должна быть написана.

    Сторож соседний, и стоит он здесь не от сегодняшней беды: сегодня
    миграция как раз **была** написана и не была применена к базе
    разработки, а этого ни один тест увидеть не может — и `manage.py test`,
    и стенд браузерных тестов поднимают базу с нуля и мигрируют её целиком.
    Единственная база, которая умеет отставать, — долгоживущая dev, и по
    ней не гоняется ничего.

    А вот обратный случай — поле в модели есть, миграции нет — ловится
    отсюда и стоит дёшево: расхождение доедет до прода как падающий
    `migrate` при старте контейнера.
    """

    # `makemigrations` сверяет историю миграций с базой, то есть ходит в
    # неё; без этого `SimpleTestCase` запрещает запрос
    databases = {"default"}

    def test_the_models_have_no_changes_left_without_a_migration(self):
        out = StringIO()
        try:
            call_command(
                "makemigrations", "--check", "--dry-run", stdout=out, stderr=out
            )
        except SystemExit:
            self.fail(f"модель изменена без миграции:\n{out.getvalue()}")
