"""
Копирование к себе и семьи аналогов.

Две операции, которые легко перепутать и которые значат совершенно разное:

* **скопировать** задачу из общего каталога в свою книгу — это про место, где
  она лежит. Копия остаётся той же задачей (или её правленой версией), и знать
  про это надо ровно затем, чтобы не выдавать её за самостоятельную работу;
* **объявить аналогом** — это про условие: та же задача с другими числами.
  Аналог пишут заново, и происхождения у него нет вовсе.

Смешать их значило бы получить семью из задачи и трёх её же копий, где искать
нечего.

И у копирования два вида, тоже разных:

|            | что происходит | когда нужно |
|------------|----------------|-------------|
| **ссылка** | новая строка в моей книге, задача та же | «хочу этот номер у себя под рукой» |
| **своя копия** | новое условие с пометкой «произошла от» | «возьму и поправлю числа» |

Ссылка по умолчанию: чаще всего задачу берут как есть, а лишняя копия в базе
означает, что правка оригинала до неё не дойдёт.
"""

from config.errors import Codes, api_error
from django.db import transaction

from .models import Entry, Family, Problem, Section, Source

LINK = "link"
FORK = "fork"


def copy_problem(problem, *, into, mode=LINK, label="", section=None, user):
    """Задача — в мою книгу: ссылкой или своей копией."""
    _refuse_if_alien_section(section, into)

    with transaction.atomic():
        made = _fork(problem, into, user) if mode == FORK else problem
        return Entry.objects.create(
            source=into,
            section=section,
            problem=made,
            label=label or _label_of(problem),
            position=into.entries.count(),
        )


def copy_section(section, *, into, mode=LINK, user):
    """
    Раздел целиком — со всеми задачами и вложенными разделами.

    Берут обычно главу, а не задачу: «этот параграф мне на весь год». Порядок
    внутри сохраняется — по нему главу и читают.
    """
    with transaction.atomic():
        return _copy_section(section, into=into, parent=None, mode=mode, user=user)


def _copy_section(section, *, into, parent, mode, user):
    made = Section.objects.create(
        source=into,
        parent=parent,
        title=section.title,
        position=into.sections.filter(parent=parent).count(),
    )
    start = into.entries.count()
    for offset, entry in enumerate(section.entries.select_related("problem")):
        Entry.objects.create(
            source=into,
            section=made,
            problem=_fork(entry.problem, into, user) if mode == FORK else entry.problem,
            label=entry.label,
            page=entry.page,
            position=start + offset,
        )
    for child in section.children.all():
        _copy_section(child, into=into, parent=made, mode=mode, user=user)
    return made


def _fork(problem, into, user):
    """
    Своя копия: то же условие, но **владение у неё от книги**, а не от
    оригинала. Иначе копия системной задачи в личной книге осталась бы
    системной, и править её человек не смог бы — то есть копировал он зря.
    """
    return Problem.objects.create(
        school=into.school,
        owner=into.owner,
        created_by=user,
        text=problem.text,
        answer=problem.answer,
        copied_from=problem,
    )


def _label_of(problem):
    """Номер берётся у первой встречи: «то же, что было там, откуда взяли»."""
    entry = problem.entries.first()
    return entry.label if entry else ""


def _refuse_if_alien_section(section, into):
    if section is not None and section.source_id != into.pk:
        raise api_error(
            Codes.BANK_READ_ONLY, "Раздел из другой книги здесь ничего не значит."
        )


def join_family(problem, other, *, user):
    """
    Объявить две задачи аналогами.

    Семьи **сливаются**, а не вкладываются: аналогичность транзитивна, и после
    «A аналог B» все аналоги A становятся аналогами B — иначе одно и то же
    условие лежало бы в двух семьях, и «показать аналоги» отвечало бы
    по-разному, смотря с какой стороны спросить.
    """
    if problem.pk == other.pk:
        raise api_error(
            Codes.BANK_SAME_PROBLEM, "Задача не аналог самой себе."
        )

    with transaction.atomic():
        family = problem.family or other.family or Family.objects.create(created_by=user)
        losing = {problem.family_id, other.family_id} - {family.pk, None}

        Problem.objects.filter(pk__in=[problem.pk, other.pk]).update(family=family)
        if losing:
            Problem.objects.filter(family_id__in=losing).update(family=family)
            Family.objects.filter(pk__in=losing).delete()
        return family


def leave_family(problem):
    """
    Выйти из семьи. Оставшийся в одиночестве не считается семьёй: одна задача
    без аналогов и задача, у которой аналогов не бывает, — одно состояние.
    """
    family_id = problem.family_id
    if not family_id:
        return

    Problem.objects.filter(pk=problem.pk).update(family=None)
    left = Problem.objects.filter(family_id=family_id)
    if left.count() < 2:
        left.update(family=None)
        Family.objects.filter(pk=family_id).delete()
