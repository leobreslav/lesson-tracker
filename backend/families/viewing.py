"""
Чьими глазами смотрим на ученические экраны.

Один вопрос, один ответ, одно место. Экранов у ученика четыре — курсы, курс,
работы, работа, — и родителю нужны все четыре, но про **ребёнка**. Спросить
«чей это экран» в каждом из четырёх значило бы написать правило четырежды и
однажды забыть его в пятом: забытое место открыло бы родителю чужого ребёнка,
и обнаружилось бы это не тестом, а родителем.
"""

from config.errors import Codes, api_error

from .models import Guardianship


def children_of(parent):
    """Дети этого родителя, по алфавиту. Пустой список — законное состояние."""
    return [
        row.child
        for row in Guardianship.objects.filter(parent=parent).select_related("child")
    ]


def subject_of(request):
    """
    Ученик, про которого спрашивают.

    Ученик спрашивает про себя, и `?child=` у него не спрашивается вовсе:
    разрешить ему назвать чужой номер — значит завести дыру ради симметрии.

    Родитель называет ребёнка параметром. Умолчание есть ровно в одном случае —
    когда ребёнок один: тогда вопрос «чей экран» не имеет второго ответа, и
    требовать его было бы придиркой. Детей несколько и никто не назван — это
    отказ (`child_required`), а не «покажем первого по алфавиту»: молча выбрать
    за родителя, про кого он спрашивает, хуже, чем переспросить.

    **Чужой ребёнок — тот же отказ, что несуществующий.** Различать «нет
    такого ученика» и «есть, но не ваш» значило бы отвечать на вопрос, кто
    учится в школе, тому, кто спрашивать об этом не должен.
    """
    user = request.user

    if user.is_student:
        return user

    named = request.query_params.get("child") or request.data.get("child")
    mine = children_of(user)

    if named in (None, ""):
        if len(mine) == 1:
            return mine[0]
        api_error(
            Codes.CHILD_REQUIRED,
            "Say which child this is about.",
            field="child",
            children=len(mine),
        )

    for child in mine:
        if str(child.pk) == str(named):
            return child

    api_error(
        Codes.NOT_YOUR_CHILD,
        "No such child of yours.",
        field="child",
    )
