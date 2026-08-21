"""
Предложения: разговор пользователя с теми, кто вправе править.

Общий каталог и словарь тегов закрыты намеренно, и цена этой закрытости была
названа с самого начала: учитель, нашедший опечатку в системной задаче или
знающий недостающий тег, не мог сделать ничего, кроме копии — то есть дубля в
общем каталоге. Здесь эта цена и погашается.

Три правила, на которых всё стоит:

1. **Кому идёт — выводится из владения**, а не хранится. Системное разбирает
   суперпользователь, школьное — администраторы школы. Поле «адресат» было бы
   вторым источником правды и разошлось бы с владением в первый же переезд.
2. **Принятие делает дело.** Опечатка вписывается, тег вешается, задача
   заводится. Предложение, после которого администратору надо ещё раз сделать
   то же самое руками, никто не станет ни писать, ни разбирать.
3. **Отказ требует слов.** Молчаливое «отклонено» — загадка, а не ответ; то же
   правило, что у возврата плана методистом.
"""

from bank.models import (
    ON_PROBLEM,
    ON_SOLUTION,
    NEGATABLE,
    Problem,
    ProblemTag,
    Proposal,
    ProposalNote,
    Solution,
    SolutionTag,
    Tag,
)
from bank.owning import SCHOOL, SYSTEM
from config.errors import Codes, api_error
from django.db import transaction
from django.utils import timezone


def addressed_to(proposal) -> str:
    """
    Кто это разбирает: `system` или `school`.

    Считается по тому, о чём речь: у предложения про существующий объект
    уровень берётся у него самого, у новой задачи — тот, что назвал автор.
    """
    target = proposal.solution or proposal.problem or proposal.tag
    if target is None:
        return proposal.level

    if isinstance(target, Tag):
        # словарь общий, и правит его только суперпользователь
        return SYSTEM
    return target.level if target.level != "personal" else SCHOOL


def may_resolve(user, proposal) -> bool:
    """
    Кому можно разобрать. Роль, а не членство: администратор школы разбирает
    школьные предложения своей школы, суперпользователь — всё.
    """
    if user.is_superuser:
        return True
    if addressed_to(proposal) == SYSTEM:
        return False
    return bool(
        user.is_school_admin and proposal.school_id and proposal.school_id == user.school_id
    )


def waiting_for(user):
    """
    Очередь разбора этого человека.

    Суперпользователю — системные, администратору — школьные его школы,
    остальным — пусто: разбирать им нечего, и показывать чужую очередь значит
    обещать действие, которого не будет.
    """
    found = Proposal.objects.filter(state=Proposal.PENDING).select_related(
        "problem", "solution", "tag", "author"
    )
    if user.is_superuser:
        return found
    if user.is_school_admin and user.school_id:
        return [
            one
            for one in found.filter(school=user.school)
            if addressed_to(one) != SYSTEM
        ]
    return []


def make(user, *, kind, text="", suggested="", problem=None, solution=None, tag=None, level=None):
    """
    Завести предложение.

    Уровень спрашивается только у новой задачи — у остальных он известен из
    того, о чём речь, и присланное значение не должно его перебивать: иначе
    предложение про системную задачу можно было бы адресовать своей школе,
    где его никто не вправе применить.
    """
    if not text.strip() and not suggested.strip():
        raise api_error(
            Codes.PROPOSAL_EMPTY,
            "Скажите, в чём дело: пустое предложение разобрать нельзя.",
            field="text",
        )

    proposal = Proposal(
        kind=kind,
        problem=problem,
        solution=solution,
        tag=tag,
        text=text.strip(),
        suggested=suggested.strip(),
        author=user,
        school=user.school,
        level=level or SCHOOL,
    )
    proposal.level = addressed_to(proposal)
    proposal.save()
    return proposal


def say(proposal, user, text: str) -> ProposalNote:
    """
    Реплика в разговоре. Пишут обе стороны: половина предложений — не «да/нет»,
    а «а что именно не так».
    """
    if not text.strip():
        raise api_error(
            Codes.MESSAGE_EMPTY, "Пустая реплика — не реплика.", field="text"
        )
    return ProposalNote.objects.create(proposal=proposal, author=user, text=text.strip())


def accept(proposal, user, *, answer="", tag_kind=None, side=None):
    """
    Принять — и **сделать то, что предложено**.

    Возвращает то, что появилось (условие, разбор, тег) или `None`, если
    делать было нечего. Всё одной транзакцией: принятое наполовину — это
    предложение, помеченное принятым, после которого ничего не изменилось.
    """
    made = None
    with transaction.atomic():
        if proposal.kind == Proposal.TYPO:
            made = _fix(proposal)
        elif proposal.kind == Proposal.TAG:
            made = _mark(proposal, tag_kind=tag_kind, side=side)
        elif proposal.kind == Proposal.PROBLEM:
            made = _add_problem(proposal)
        elif proposal.kind == Proposal.SOLUTION:
            made = _add_solution(proposal)

        proposal.state = Proposal.ACCEPTED
        proposal.answer = answer.strip()
        proposal.resolved_by = user
        proposal.resolved_at = timezone.now()
        proposal.save()

    return made


def decline(proposal, user, *, answer=""):
    """Отклонить — со словами: отказ молчком это загадка, а не ответ."""
    if not answer.strip():
        raise api_error(
            Codes.PROPOSAL_ANSWER_REQUIRED,
            "Скажите, почему не подходит: отказ молчком объяснить некому.",
            field="answer",
        )

    proposal.state = Proposal.DECLINED
    proposal.answer = answer.strip()
    proposal.resolved_by = user
    proposal.resolved_at = timezone.now()
    proposal.save()
    return proposal


def _fix(proposal):
    """Опечатка: вписываем предложенный текст, если он есть."""
    if not proposal.suggested:
        return None

    target = proposal.solution or proposal.problem
    if target is None:
        return None

    target.text = proposal.suggested
    target.save(update_fields=["text"])
    return target


def _mark(proposal, *, tag_kind, side):
    """
    Тег: вешаем существующий или заводим новый по имени.

    Вид нового тега называет **разбирающий**, а не предлагающий: словарь
    складывается в папки по видам, и вид — это решение того, кто его ведёт.
    """
    tag = proposal.tag
    if tag is None:
        if not proposal.suggested:
            return None
        if not tag_kind:
            raise api_error(
                Codes.TAG_KIND_REQUIRED,
                "Скажите, какого вида этот тег: словарь разложен по видам.",
                field="kind",
            )
        tag, _ = Tag.objects.get_or_create(name=proposal.suggested, kind=tag_kind)

    if proposal.solution_id:
        if tag.kind not in ON_SOLUTION:
            api_error(
                Codes.TAG_KIND_MISMATCH,
                "Тег этого вида ставится на условие, а не на разбор.",
                field="tag",
            )
        chosen = side or SolutionTag.USES
        if chosen == SolutionTag.AVOIDS and tag.kind not in NEGATABLE:
            api_error(
                Codes.TAG_NOT_NEGATABLE,
                "Отрицать можно только метод или теорему.",
                field="side",
            )
        SolutionTag.objects.get_or_create(
            solution=proposal.solution, tag=tag, defaults={"side": chosen}
        )
    elif proposal.problem_id:
        if tag.kind not in ON_PROBLEM:
            api_error(
                Codes.TAG_KIND_MISMATCH,
                "Тег этого вида ставится на разбор, а не на условие.",
                field="tag",
            )
        ProblemTag.objects.get_or_create(problem=proposal.problem, tag=tag)

    return tag


def _add_problem(proposal):
    """
    Задача: заводится на том уровне, куда предлагали, **с автором в истории**.

    `created_by` остаётся тем, кто предложил: владение и авторство — разные
    вещи, и приписывать чужую работу разбирающему нечестно.
    """
    if not proposal.suggested:
        return None

    return Problem.objects.create(
        text=proposal.suggested,
        school=None if proposal.level == SYSTEM else proposal.school,
        owner=None,
        created_by=proposal.author,
    )


def _add_solution(proposal):
    """Разбор к названной задаче, на том же уровне и с тем же авторством."""
    if not proposal.suggested or proposal.problem_id is None:
        return None

    return Solution.objects.create(
        problem=proposal.problem,
        text=proposal.suggested,
        school=None if proposal.level == SYSTEM else proposal.school,
        owner=None,
        created_by=proposal.author,
    )


def payload(proposal, *, user) -> dict:
    return {
        "id": proposal.pk,
        "kind": proposal.kind,
        "state": proposal.state,
        "level": addressed_to(proposal),
        "text": proposal.text,
        "suggested": proposal.suggested,
        "answer": proposal.answer,
        "problem": proposal.problem_id,
        "solution": proposal.solution_id,
        "tag": proposal.tag.name if proposal.tag_id else "",
        "about": _about(proposal),
        "author": proposal.author.email if proposal.author_id else "",
        "created_at": proposal.created_at,
        "may_resolve": may_resolve(user, proposal),
        "notes": [
            {
                "id": note.pk,
                "text": note.text,
                "author": note.author.email if note.author_id else "",
                "when": note.created_at,
            }
            for note in proposal.notes.select_related("author")
        ],
    }


def _about(proposal) -> str:
    """О чём речь — одной строкой, чтобы очередь читалась без переходов."""
    if proposal.solution_id:
        return proposal.solution.text[:80]
    if proposal.problem_id:
        return proposal.problem.text[:80]
    if proposal.tag_id:
        return proposal.tag.name
    return ""
