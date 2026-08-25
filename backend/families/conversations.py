"""
С кем семье есть о чём говорить.

Сама переписка отсюда ушла — она оказалась не семейной вещью, а общей: коллега,
ученик, родитель различаются не природой разговора, а поводом. Живёт она теперь
в `talks`, а здесь остался единственный вопрос, на который может ответить
только этот модуль: **кто ведёт курсы этого ребёнка**. Им и решается, кому
семья вправе написать.
"""

from schedule.models import CourseAssignment, CourseStudent


def teachers_for(child):
    """
    С кем родителю есть о чём говорить: ведущие курсов, где ребёнок учится.

    Берутся **действующие** зачисления: список «кому написать» — это про
    сегодня, а прошлогодний учитель в нём был бы предложением, за которым
    ничего не стоит. Прежние разговоры при этом никуда не деваются и
    читаются — они уже состоялись.
    """
    courses = CourseStudent.objects.filter(
        student=child, removed_at__isnull=True
    ).values_list("course_id", flat=True)

    # Курс в таблице назначений встречается один раз (`one_teacher_per_course`),
    # но `related_name` у неё множественный, и полагаться на «ровно один» тут
    # незачем: берём всех, кто там стоит, и схлопываем повторы — один учитель
    # ведёт у ребёнка и алгебру, и геометрию.
    seen, out = set(), []
    for row in (
        CourseAssignment.objects.filter(course_id__in=courses)
        .select_related("teacher")
        .order_by("teacher__last_name", "teacher__email")
    ):
        if row.teacher_id in seen:
            continue
        seen.add(row.teacher_id)
        out.append(row.teacher)
    return out
