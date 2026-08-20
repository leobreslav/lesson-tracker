"""
Хронология плана и темы, заданные условием.

Здесь сходятся две вещи, которые до сих пор жили порознь: **учебный план** —
что и когда проходят, — и **разметка решений** — чем разбор пользуется. Связаны
они одной таблицей `Introduction`: «этот урок вводит это понятие». Из неё
получается ответ на вопрос, ради которого всё и затевалось: **какие задачи
класс умеет решать к такому-то дню**.

Ключевое слово тут «умеет», а не «проходил»: умение считается по решениям, а не
по условиям. Условие «решите уравнение» ничего не говорит о средствах; средства
называет разбор, поэтому и тема — это набор **разборов**, а задачи в неё
попадают через них.

Закрытость темы — отдельный флаг, и это самое тонкое место. Открытая тема
спрашивает «пользуется ли разбор вот этим»; закрытая — ещё и «не пользуется ли
он ничем сверх пройденного». Второе нужно ровно для «дайте задач на сейчас»:
разбор через производную формально пользуется квадратным трёхчленом, но
шестикласснику он бесполезен.
"""

from django.db.models import Count, Exists, OuterRef

from .models import Introduction, Problem, Solution, SolutionTag, Tag, Topic


def introduce(course, node, tag):
    """
    Отметить, что урок вводит понятие. Повторное — **переносит**, а не двоит:
    понятие вводится однажды, и вторая отметка означает, что первая была не там.
    """
    row, made = Introduction.objects.get_or_create(
        course=course, tag=tag, defaults={"node": node}
    )
    if not made and row.node_id != node.pk:
        row.node = node
        row.save(update_fields=["node"])
    return row


def introduced(course, *, upto=None) -> set[int]:
    """
    Что пройдено к этому уроку включительно.

    Порядок берётся у самого плана — сквозной номер урока, — а не у дат: даты
    зависят от расписания, а хронология понятий это свойство программы.
    Отменённое занятие ничего не отменяет в том, что уже прошли.
    """
    rows = Introduction.objects.filter(course=course).select_related("node")
    if upto is None:
        return {row.tag_id for row in rows}

    order = _order(course)
    limit = order.get(upto.pk)
    if limit is None:
        return {row.tag_id for row in rows}
    return {row.tag_id for row in rows if order.get(row.node_id, 0) <= limit}


def _order(course) -> dict[int, int]:
    """Сквозной порядок строк плана: тем же обходом, что и нумерация уроков."""
    from plans import services as plan_services

    return {
        lesson.node.pk: lesson.number
        for lesson in plan_services.flatten_lessons(course.pk)
    }


def solutions_in(topic, *, user, course=None, upto=None):
    """
    Разборы темы — из того, что человеку видно.

    Суть складывается «и»: тема это пересечение средств. Запрещённое
    отсекается. Закрытая тема вдобавок требует, чтобы **ни одного** чужого
    средства в разборе не было.
    """
    found = Solution.objects.visible_to(user).filter(retired=False)

    needed = list(topic.essence.values_list("pk", flat=True))
    for tag_id in needed:
        found = found.filter(links__tag_id=tag_id, links__side=SolutionTag.USES)

    for tag_id in topic.forbidden.values_list("pk", flat=True):
        found = found.exclude(links__tag_id=tag_id, links__side=SolutionTag.USES)

    if topic.closed:
        allowed = set(needed)
        if course is not None:
            allowed |= introduced(course, upto=upto)
        # «Пользуется чем-то сверх дозволенного» — это существование связи с
        # тегом не из списка. Спрашивается оно подзапросом, и иначе нельзя:
        # `exclude(~Q(...), ...)` на многозначной связи соединяет условия не с
        # той строкой и отвечает «ничего не нашлось» молча.
        outside = SolutionTag.objects.filter(
            solution=OuterRef("pk"), side=SolutionTag.USES
        ).exclude(tag_id__in=allowed)
        found = found.filter(~Exists(outside))

    return found.distinct()


def problems_in(topic, **kwargs):
    """Задачи темы — те, у которых есть подходящий разбор."""
    user = kwargs["user"]
    solutions = solutions_in(topic, **kwargs)
    return (
        Problem.objects.visible_to(user)
        .filter(retired=False, pk__in=solutions.values("problem_id"))
        .distinct()
    )


def tree(course=None, *, upto=None):
    """Темы деревом, с числом разборов у каждой — как оглавление у книги."""
    counted = {
        row["pk"]: row["how_many"]
        for row in Topic.objects.values("pk").annotate(how_many=Count("essence"))
    }
    depth = {}
    out = []
    for topic in Topic.objects.all().order_by("position", "title", "id"):
        depth[topic.pk] = depth.get(topic.parent_id, -1) + 1
        out.append(
            {
                "id": topic.pk,
                "title": topic.title,
                "parent": topic.parent_id,
                "depth": depth[topic.pk],
                "closed": topic.closed,
                "essence": counted.get(topic.pk, 0),
            }
        )
    return out


def chronology(course) -> list[dict]:
    """
    План курса как хронология: строка плана и понятия, которые она вводит.

    Отдаётся целиком, а не по уроку: смысл у этого списка появляется, только
    когда видно порядок, — «производная в марте, а задача на неё в октябре».
    """
    from plans import services as plan_services

    rows = {}
    for row in Introduction.objects.filter(course=course).select_related("tag"):
        rows.setdefault(row.node_id, []).append(
            {"id": row.tag_id, "name": row.tag.name, "kind": row.tag.kind}
        )

    return [
        {
            "node": lesson.node.pk,
            "number": lesson.number,
            "title": lesson.node.title,
            "section": lesson.section.title if lesson.section else None,
            "tags": rows.get(lesson.node.pk, []),
        }
        for lesson in plan_services.flatten_lessons(course.pk)
    ]


__all__ = [
    "introduce",
    "introduced",
    "solutions_in",
    "problems_in",
    "tree",
    "chronology",
    "Tag",
    "Topic",
]
