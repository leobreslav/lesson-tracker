"""
Кому можно написать и кто читает разговор.

Вопрос один — «есть ли вам о чём говорить», — а ответов три, по видам
собеседников. Живут они здесь все вместе именно потому, что вопрос один:
разложенные по экранам, они разошлись бы молча, и узнал бы об этом человек,
получивший письмо от незнакомца.

* **сотрудник сотруднику** — свободно внутри школы. Коллеги и так видят друг
  друга в справочнике, работают в одних классах и сталкиваются в коридоре;
  разрешение «только по общим курсам» отсекло бы ровно те разговоры, ради
  которых мессенджер и заводят («у тебя есть свободный кабинет во вторник?»);
* **семья учителю** — по участию: ученик пишет ведущим своих курсов, родитель
  — ведущим курсов своего ребёнка. Справочник вместо этого списка означал бы
  письма учителю по поводу, к нему не относящемуся;
* **семья семье** — нельзя. Ни ученик ученику, ни родитель родителю: школьный
  журнал не социальная сеть, и переписку одноклассников в нём никто не
  модерирует. Отказ тут не техническое ограничение, а решение, и оно
  осознанное.

Читает разговор **участник**, и больше никто — включая администратора школы.
Разговор двух людей это не содержимое курса: чинить в нём нечего.
"""

from config.errors import Codes, api_denied
from django.db.models import Q

from .models import Talk


def partners(user) -> list:
    """
    Кому этот человек может написать первым, в порядке показа.

    Список, а не проверка: экран показывает его целиком — иначе «кому можно»
    выясняется методом тыка. Проверка (`refuse_unless_allowed`) считает по
    этому же списку, чтобы экран и сервер не разошлись.
    """
    from accounts.models import User

    if user.school_id is None:
        return []

    if user.is_teacher:
        # Все сотрудники школы, кроме себя. Ученики и родители сюда не
        # попадают намеренно: разговор с семьёй заводит семья — так у неё
        # остаётся возможность не начинать его вовсе.
        return list(
            User.objects.filter(school_id=user.school_id, kind=User.Kind.TEACHER)
            .exclude(pk=user.pk)
            .order_by("last_name", "first_name", "email")
        )

    return _teachers_of(user)


def _teachers_of(user) -> list:
    """Ведущие курсов, где учится сам человек или его ребёнок."""
    from families.conversations import teachers_for
    from families.viewing import children_of

    if user.is_student:
        return teachers_for(user)

    if user.is_parent:
        seen, out = set(), []
        for child in children_of(user):
            for teacher in teachers_for(child):
                if teacher.pk not in seen:
                    seen.add(teacher.pk)
                    out.append(teacher)
        return out

    return []


def may_write_to(user, other) -> bool:
    """Есть ли этим двоим о чём говорить. Симметрично по построению."""
    if user.pk == other.pk or user.school_id != other.school_id:
        return False

    if user.is_teacher and other.is_teacher:
        return True

    # Разные стороны: одна из них семья, и решает участие. Спрашиваем со
    # стороны семьи — у неё список короткий и осмысленный.
    family, staff = (user, other) if user.is_family else (other, user)
    if not staff.is_teacher or not family.is_family:
        return False

    return staff.pk in {one.pk for one in _teachers_of(family)}


def refuse_unless_allowed(user, other) -> None:
    if not may_write_to(user, other):
        api_denied(
            Codes.NOT_A_TEACHER_OF_THIS_CHILD,
            "There is nothing for the two of you to talk about here.",
        )


def my_talks(user):
    """Разговоры, в которых этот человек участвует."""
    if user is None or not user.is_authenticated:
        return Talk.objects.none()

    return Talk.objects.filter(Q(lower=user) | Q(upper=user))


def may_read(user, talk) -> bool:
    """Участник — и никто больше, администратор школы включительно."""
    return user.pk in (talk.lower_id, talk.upper_id)
