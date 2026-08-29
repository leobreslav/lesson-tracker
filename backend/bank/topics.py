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

Закрытость темы — не флаг, а лист выражения (`{"solution": {"covered": true}}`),
и это самое тонкое место. Обычная тема спрашивает «пользуется ли разбор вот
этим»; закрытая — ещё и «не пользуется ли он ничем сверх пройденного». Второе
нужно ровно для «дайте задач на сейчас»: разбор через производную формально
пользуется квадратным трёхчленом, но шестикласснику он бесполезен.
"""

from .models import Introduction, Topic


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
    from plans.owning import of_course

    return {
        lesson.node.pk: lesson.number
        for lesson in plan_services.flatten_lessons(of_course(course))
    }


def covered(course, upto=None) -> set:
    """Что пройдено к этому уроку — то же, что `introduced`, но именем яснее."""
    return introduced(course, upto=upto)


def tree(found, mine) -> list[dict]:
    """
    Темы деревом: плоский список с уровнями, как оглавление книги.

    Уровень считается по родителю, а не по владению: дерево общее, и своя
    ветка внутри общей темы стоит там, где её положили.
    """
    by_id = {topic.pk: topic for topic in found}
    depth = {}

    def deep(topic):
        if topic.pk in depth:
            return depth[topic.pk]
        parent = by_id.get(topic.parent_id)
        depth[topic.pk] = 0 if parent is None else deep(parent) + 1
        return depth[topic.pk]

    ordered = sorted(found, key=lambda topic: (deep(topic), topic.position, topic.title))
    return [payload(topic, mine=topic.pk in mine, depth=deep(topic)) for topic in ordered]


def payload(topic, *, mine, depth=0) -> dict:
    return {
        "id": topic.pk,
        "title": topic.title,
        "parent": topic.parent_id,
        "depth": depth,
        "level": topic.level,
        "expression": topic.expression,
        "may_edit": mine,
    }


def remove(topic) -> None:
    """
    Убрать тему, **впечатав** её условие в детей.

    Иначе ветка, висевшая на удалённой, молча стала бы шире, чем была, и
    человек узнал бы об этом по чужим задачам в ней.
    """
    from django.db import transaction

    with transaction.atomic():
        for child in topic.children.all():
            parts = [
                part
                for part in (topic.expression, child.expression)
                if part
            ]
            child.expression = (
                {} if not parts else parts[0] if len(parts) == 1 else {"all": parts}
            )
            child.parent = topic.parent
            child.save(update_fields=["expression", "parent"])
        topic.delete()


def chronology(course) -> list[dict]:
    """
    План курса как хронология: строка плана и понятия, которые она вводит.

    Отдаётся целиком, а не по уроку: смысл у этого списка появляется, только
    когда видно порядок, — «производная в марте, а задача на неё в октябре».
    """
    from plans import services as plan_services
    from plans.owning import of_course

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
        for lesson in plan_services.flatten_lessons(of_course(course))
    ]


__all__ = ["introduce", "introduced", "covered", "tree", "payload", "remove", "chronology", "Topic"]
