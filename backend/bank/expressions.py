"""
Логическое выражение из граней — и запрос, который можно назвать и сохранить.

Фасетный поиск отвечает на «алгебра **и** многочлен **и** не сложнее такого-то»
— то есть только на «и». А спрашивают и другое: «уравнение или неравенство, но
без производной». Выразить это гранями нельзя вовсе, поэтому рядом с ними стоит
второй вход — дерево.

Форма дерева:

    {"all": [узел, ...]}          все условия сразу
    {"any": [узел, ...]}          хотя бы одно
    {"not": узел}                 отрицание целиком
    {"tag": 12}                   тег на условии
    {"text": "окружность"}        слово в условии
    {"solution": {...}}           существует разбор, который …

Лист «разбор» держит все требования к **одному** разбору сразу:

    {"solution": {"uses": [12, 15], "avoids": [7], "covered": true}}

Иначе они разъезжаются: «через Виета» и «без дискриминанта», спрошенные
порознь, найдут задачу, у которой это два **разных** разбора, — то есть набор,
в котором ни одного нужного решения нет. Ровно так же спрашивает фасетный
поиск, и правило у них одно.

`covered` — «разбор не выходит за пройденное»: все его средства внутри того,
что курс к этому уроку прошёл. Это единственный лист с параметром: пройденное
приходит извне, из хронологии плана, и спрашивает его экран.

Правило разбора то же, что у разбора CSV и списка класса: **вместо угадывания
отказ**. Узел, которого мы не знаем, — это не «пропустим», а ошибка с адресом:
молча выброшенное условие делает поиск шире, чем просили, и заметить это нельзя
ничем.

Отдельная тонкость про отрицание: лист компилируется в `Exists`, а не в
`filter` по связи. На многозначной связи `~Q(links__tag=5)` читается как «есть
связь не с этим тегом» — то есть отрицание получает не тот смысл, и получает
его молча.
"""

from config.errors import Codes, api_error
from django.db.models import Exists, OuterRef, Q

from .models import Problem, ProblemTag, Solution, SolutionTag

DEPTH = 6


def compile_(node, *, where="запрос", depth=0, allowed=None):
    """
    Дерево → `Q`. Кривой узел отклоняется с адресом внутри выражения.

    `allowed` — множество пройденных тегов; нужно только листу «разбор» с
    `covered`, и его отсутствие там значит «ничего не пройдено».
    """
    if depth > DEPTH:
        raise api_error(
            Codes.BANK_EXPRESSION_BAD,
            f"Выражение вложено слишком глубоко ({where}).",
        )
    if not isinstance(node, dict) or len(node) == 0:
        raise api_error(
            Codes.BANK_EXPRESSION_BAD, f"Здесь ожидалось условие ({where})."
        )

    if "all" in node or "any" in node:
        every = "all" in node
        parts = node["all"] if every else node["any"]
        if not isinstance(parts, list) or not parts:
            raise api_error(
                Codes.BANK_EXPRESSION_BAD, f"Группа пустая ({where})."
            )
        made = [
            compile_(
                part, where=f"{where} → {number + 1}", depth=depth + 1, allowed=allowed
            )
            for number, part in enumerate(parts)
        ]
        joined = made[0]
        for part in made[1:]:
            joined = joined & part if every else joined | part
        return joined

    if "not" in node:
        return ~compile_(
            node["not"], where=f"{where} → не", depth=depth + 1, allowed=allowed
        )

    if "text" in node:
        word = str(node["text"]).strip()
        if not word:
            raise api_error(Codes.BANK_EXPRESSION_BAD, f"Слово пустое ({where}).")
        return Q(text__icontains=word)

    if "solution" in node:
        return _solution(node["solution"], where, allowed)

    if "tag" in node:
        return _tag(node, where)

    raise api_error(
        Codes.BANK_EXPRESSION_BAD, f"Непонятное условие ({where}): {list(node)[0]}."
    )


def _tag(node, where):
    try:
        tag_id = int(node["tag"])
    except (TypeError, ValueError):
        raise api_error(Codes.BANK_EXPRESSION_BAD, f"Тег не числом ({where}).")

    side = node.get("side") or ""
    if not side:
        return Exists(ProblemTag.objects.filter(problem=OuterRef("pk"), tag_id=tag_id))
    if side not in (SolutionTag.USES, SolutionTag.AVOIDS):
        raise api_error(Codes.BANK_EXPRESSION_BAD, f"Непонятная сторона ({where}).")
    return Exists(
        Solution.objects.filter(
            problem=OuterRef("pk"), links__tag_id=tag_id, links__side=side
        )
    )


def _solution(wanted, where, allowed):
    """
    «Существует разбор, который…» — все требования к одному разбору сразу.

    Запрещённое отсекается **исключением по этому же разбору**, а не отдельным
    условием: «пользуется Виетом и при этом не пользуется дискриминантом» —
    утверждение об одном тексте.
    """
    if not isinstance(wanted, dict):
        raise api_error(
            Codes.BANK_EXPRESSION_BAD, f"Условие на разбор не словарь ({where})."
        )

    found = Solution.objects.filter(problem=OuterRef("pk"), retired=False)
    for tag_id in wanted.get("uses") or []:
        found = found.filter(links__tag_id=tag_id, links__side=SolutionTag.USES)
    for tag_id in wanted.get("avoids") or []:
        found = found.filter(links__tag_id=tag_id, links__side=SolutionTag.AVOIDS)

    if wanted.get("covered"):
        # Средства, названные в самом условии, дозволены по определению: тема
        # про квадратные уравнения не обязана ждать, пока «квадратное
        # уравнение» появится в хронологии — она про него и есть.
        allowed = set(allowed or []) | set(wanted.get("uses") or [])
        # «Не выходит за пройденное» — это отсутствие связи с чем-то, чего мы
        # ещё не проходили. Спрашивается подзапросом, и иначе нельзя:
        # `exclude(~Q(...), ...)` на многозначной связи соединяет условия не с
        # той строкой и отвечает «ничего не нашлось» молча.
        outside = SolutionTag.objects.filter(
            solution=OuterRef("pk"), side=SolutionTag.USES
        ).exclude(tag_id__in=allowed or [])
        found = found.filter(~Exists(outside))

    return Exists(found)


def mentions_covered(node) -> bool:
    """Спрашивать ли курс и урок: пройденное приходит только оттуда."""
    if not isinstance(node, dict):
        return False
    if isinstance(node.get("solution"), dict) and node["solution"].get("covered"):
        return True
    if "not" in node and mentions_covered(node["not"]):
        return True
    return any(
        mentions_covered(part)
        for key in ("all", "any")
        for part in (node.get(key) or [])
    )


def find(user, node, *, allowed=None):
    """Задачи, отвечающие выражению, — из того, что человеку видно."""
    return (
        Problem.objects.visible_to(user)
        .filter(retired=False)
        .filter(compile_(node, allowed=allowed))
        .distinct()
    )


def mentioned(node, into=None):
    """
    Теги, названные в выражении: их незачем предлагать гранями рядом.

    Считается обходом самого дерева, а не запросом: выражение уже на руках.
    """
    into = into if into is not None else {"": set(), "uses": set(), "avoids": set()}
    if not isinstance(node, dict):
        return into
    for key in ("all", "any"):
        for part in node.get(key) or []:
            mentioned(part, into)
    if "not" in node:
        mentioned(node["not"], into)
    if "tag" in node:
        try:
            into[node.get("side") or ""].add(int(node["tag"]))
        except (TypeError, ValueError, KeyError):
            pass
    return into
