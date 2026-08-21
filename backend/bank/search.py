"""
Поиск задачи по граням и по тексту.

Гранью тут называется тег, добавленный к запросу: каждый следующий сужает
набор, а рядом с невыбранными стоит число — сколько останется, если добавить
и его. Список без чисел бесполезен: половина тегов словаря к текущему набору
не подходит вовсе, и выбирать пришлось бы вслепую.

Главное решение внутри — **грани решения проверяются на одном решении, а не
на задаче**. «Через Виета, но без дискриминанта» это описание одного разбора;
задача, у которой есть отдельно разбор через Виета и отдельно разбор без
дискриминанта, такому запросу не отвечает. Порознь эти условия дали бы набор,
в котором ни одного нужного решения нет, — и объяснить его было бы нечем.
"""

from django.db.models import Count, Exists, OuterRef, Q

from .models import (
    ON_PROBLEM,
    ON_SOLUTION,
    Problem,
    ProblemTag,
    Solution,
    SolutionTag,
    Tag,
)

LIMIT = 60


def find(user, *, text="", tags=(), uses=(), avoids=(), level=None, shelved=None):
    """
    Задачи, отвечающие всем граням сразу. Возвращает queryset — считать по
    нему грани дешевле, чем второй раз повторять условия.

    **Задача — это лист.** Сюжет («Дан треугольник ABC») из поиска исключается:
    у него нет ни вопроса, ни ответа, и в выдаче он был бы строкой, которая
    ничего не спрашивает. А вот слово из сюжета обязано находить его пункты —
    поэтому текст ищется и на уровень выше.
    """
    found = Problem.objects.visible_to(user).filter(retired=False, parts__isnull=True)

    # Ищется только условие: эталоны лежат массивом, и `icontains` по нему
    # Postgres не даёт, а поиск задачи по её ответу — вопрос, которого никто
    # не задаёт. Зато вместе с условием ищется сюжет: «окружность» из шапки
    # обязана находить пункт «найдите радиус», где этого слова нет.
    for word in text.split():
        found = found.filter(
            Q(text__icontains=word) | Q(parent__text__icontains=word)
        )

    # каждый тег условия сужает: «многочлен и доказательство», а не «или»
    for tag_id in tags:
        found = found.filter(links__tag_id=tag_id)

    if uses or avoids:
        found = found.filter(Exists(_solutions(uses, avoids)))

    if level:
        found = found.filter(_level(level))

    if shelved == "yes":
        found = found.filter(entries__isnull=False)
    elif shelved == "no":
        found = found.filter(entries__isnull=True)

    return found.distinct()


def _solutions(uses, avoids):
    """Разбор этой задачи, отвечающий всем граням решения разом."""
    solutions = Solution.objects.filter(problem=OuterRef("pk"))
    for tag_id in uses:
        solutions = solutions.filter(links__tag_id=tag_id, links__side=SolutionTag.USES)
    for tag_id in avoids:
        solutions = solutions.filter(links__tag_id=tag_id, links__side=SolutionTag.AVOIDS)
    return solutions


def _level(level):
    if level == "system":
        return Q(school__isnull=True)
    if level == "school":
        return Q(school__isnull=False, owner__isnull=True)
    return Q(owner__isnull=False)


def facets(found, *, chosen_tags=(), chosen_uses=(), chosen_avoids=()):
    """
    Чем ещё можно сузить, с числом оставшихся у каждой грани.

    Выбранные грани в список не идут: у них число равно всему набору, и они
    выглядели бы как «ничего не сужает», хотя сузили уже.
    """
    ids = found.values("pk")

    on_problem = (
        ProblemTag.objects.filter(problem__in=ids)
        .exclude(tag_id__in=chosen_tags)
        .values("tag_id")
        .annotate(count=Count("problem_id", distinct=True))
    )
    on_solution = (
        SolutionTag.objects.filter(solution__problem__in=ids)
        .values("tag_id", "side")
        .annotate(count=Count("solution__problem_id", distinct=True))
    )

    counted = {}
    for row in on_problem:
        counted[(row["tag_id"], "")] = row["count"]
    for row in on_solution:
        chosen = chosen_uses if row["side"] == SolutionTag.USES else chosen_avoids
        if row["tag_id"] in chosen:
            continue
        counted[(row["tag_id"], row["side"])] = row["count"]

    names = {tag.pk: tag for tag in Tag.objects.filter(pk__in={key[0] for key in counted})}
    rows = [
        {
            "tag": tag_id,
            "name": names[tag_id].name,
            "kind": names[tag_id].kind,
            "side": side,
            "count": count,
        }
        for (tag_id, side), count in counted.items()
    ]
    # Сначала самые населённые: по ним набор и делится. Грань, оставляющая
    # одну задачу из четырёхсот, — не путь к ней, а случайность; искать её
    # надо словом.
    rows.sort(key=lambda row: (-row["count"], row["name"]))
    return rows


def payload(user, params):
    """Разбор запроса и ответ целиком — им пользуются и поиск, и сохранённые."""
    tags = _numbers(params.getlist("tag"))
    uses = _numbers(params.getlist("uses"))
    avoids = _numbers(params.getlist("avoids"))

    found = find(
        user,
        text=params.get("text", "").strip(),
        tags=tags,
        uses=uses,
        avoids=avoids,
        level=params.get("level") or None,
        shelved=params.get("shelved") or None,
    )
    return shape(found, chosen_tags=tags, chosen_uses=uses, chosen_avoids=avoids)


def shape(found, *, chosen_tags=(), chosen_uses=(), chosen_avoids=()):
    """
    Найденное в вид, годный для экрана.

    Общая для обоих входов — граней и выражения, — потому что показывается
    одним и тем же списком: два способа спросить, один способ ответить.
    """
    total = found.count()
    problems = list(found.select_related("family").order_by("pk")[:LIMIT])
    where = _where(problems)

    return {
        "total": total,
        "shown": len(problems),
        "problems": [
            {
                "id": problem.pk,
                "text": problem.text,
                "level": problem.level,
                "family": problem.family_id,
                # где лежит: в книге или только в работе. Отдельного признака
                # «черновая» нет — это и есть ответ на вопрос, чем набранная
                # на бегу отличается от разложенной по книгам
                "where": where.get(problem.pk),
            }
            for problem in problems
        ],
        "facets": facets(
            found,
            chosen_tags=chosen_tags,
            chosen_uses=chosen_uses,
            chosen_avoids=chosen_avoids,
        ),
    }


def _where(problems) -> dict:
    """
    Где лежит каждое из показанных условий — одним запросом на страницу.

    Книга главнее работы: если условие разложено по книгам, номер в книге и
    есть его адрес, а работы — то, где его спрашивали.
    """
    from .models import Entry

    ids = [problem.pk for problem in problems]
    found = {}

    for entry in Entry.objects.filter(problem_id__in=ids).select_related("source"):
        found.setdefault(entry.problem_id, {"kind": "book", "title": entry.source.title})

    missing = [one for one in ids if one not in found]
    if missing:
        from works.models import Task

        for task in (
            Task.objects.filter(problem_id__in=missing)
            .select_related("work")
            .order_by("work__opens_at")
        ):
            found.setdefault(
                task.problem_id, {"kind": "work", "title": task.work.title}
            )

    return found


def _numbers(values):
    """Нечисловая грань — это опечатка в адресе, а не отказ всего поиска."""
    return [int(value) for value in values if value.isdigit()]


__all__ = ["find", "facets", "payload", "shape", "LIMIT"]
