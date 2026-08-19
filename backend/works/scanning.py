"""
Разбор пачки: чья страница и что на ней написано.

Читает страницы модель, а раскладывает по ученикам этот модуль — и делает это
**независимо от порядка**. Порядок в PDF ничего не гарантирует: листы сдают
как попало, сканируют как попало, а один ученик мог взять три листа, второй
один. Правил ровно два, и оба проверяемы глазами:

1. **страница с однозначным именем** отходит своему ученику;
2. **остальные** пристраиваются по покрытию задач: страница с баллами за
   Q4..Q6 влезает туда, где этих задач ещё нет.

Что не разложилось однозначно, идёт человеку с суженными кандидатами. Это не
запасной путь, а главный: чужая контрольная, приписанная однокласснику,
дороже любой экономии на вопросах.

Похожесть считает `difflib` из стандартной библиотеки, а не rapidfuzz:
сравниваются короткие имена, разница в качестве незаметна, а зависимость
осталась бы навсегда.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Ниже этого сходства (0..100) имя вообще не считается похожим.
NEAR = 70
# Однозначным считается имя, которое похоже сильно и заметно сильнее прочих.
SURE = 85
MARGIN = 12

QUESTIONS = 15
CELLS = 16


def similarity(one: str, two: str) -> float:
    one, two = (one or "").strip().lower(), (two or "").strip().lower()
    if not one or not two:
        return 0.0
    return SequenceMatcher(None, one, two).ratio() * 100


@dataclass(frozen=True)
class Person:
    """Ученик курса глазами разбора: имя, фамилия и id."""

    id: int
    first: str
    last: str

    @property
    def full(self) -> str:
        return " ".join(x for x in (self.first, self.last) if x).strip()


@dataclass
class Page:
    """Прочитанная страница."""

    index: int
    first: str = ""
    surname: str = ""
    guess: str = ""
    cells: list = field(default_factory=lambda: [None] * CELLS)
    student_id: int | None = None
    decided_by_human: bool = False

    @property
    def named(self) -> bool:
        return bool((self.first or "").strip() or (self.surname or "").strip())

    @property
    def answered(self) -> set:
        """Номера задач (с нуля), за которые на странице стоит балл."""
        return {q for q in range(QUESTIONS) if self.cells[q] is not None}

    @property
    def page_sum(self) -> int | None:
        return self.cells[QUESTIONS] if len(self.cells) > QUESTIONS else None


def candidates_for(page: Page, roster: list[Person]) -> list[tuple[Person, float]]:
    """
    Кандидаты по доступным полям, от самого похожего.

    Поля считаются **порознь**: у страницы бывает вписано только имя или
    только фамилия, и требовать оба значило бы отправлять к человеку половину
    пачки. Когда есть оба, берётся среднее — одно совпавшее поле при втором
    чужом это не совпадение.
    """
    scored = []
    for person in roster:
        by_first = similarity(page.first, person.first)
        by_last = similarity(page.surname, person.last)
        if page.first.strip() and page.surname.strip():
            score = (by_first + by_last) / 2
        else:
            score = max(by_first, by_last)
        scored.append((person, score))
    scored.sort(key=lambda pair: -pair[1])
    return scored


def guessed(page: Page, roster: list[Person]) -> Person | None:
    """
    Кого модель назвала из списка. Строка сверяется с составом, а не берётся
    на веру: модель могла написать что угодно, а мы отвечаем за то, что этот
    человек в курсе есть.
    """
    if not page.guess:
        return None
    best, score = None, 0.0
    for person in roster:
        near = similarity(page.guess, person.full)
        if near > score:
            best, score = person, near
    return best if score >= SURE else None


def _sure(scored: list[tuple[Person, float]]) -> bool:
    """Похоже сильно и заметно сильнее второго — иначе это не однозначность."""
    if not scored or scored[0][1] < SURE:
        return False
    if len(scored) < 2:
        return True
    return scored[0][1] - scored[1][1] >= MARGIN


def group(pages: list[Page], roster: list[Person]) -> tuple[dict, list]:
    """
    Разложить страницы по ученикам.

    Возвращает `({index: student_id}, [(index, [кандидаты])])`: раскладку и
    список того, что человек должен решить сам.

    Решения человека уважаются: страница, у которой уже стоит `decided_by_human`,
    в раскладку входит как есть и в сомнения не попадает.
    """
    scored = {page.index: candidates_for(page, roster) for page in pages}
    assigned: dict[int, int] = {}
    left: list[Page] = []

    for page in pages:
        if page.decided_by_human:
            if page.student_id is not None:
                assigned[page.index] = page.student_id
            continue
        if page.named and _sure(scored[page.index]):
            assigned[page.index] = scored[page.index][0][0].id
        else:
            left.append(page)

    def covered(student_id: int) -> set:
        out: set = set()
        for page in pages:
            if assigned.get(page.index) == student_id:
                out |= page.answered
        return out

    doubts = []
    for page in left:
        mine = page.answered
        # Пустая страница ни к кому не «подходит» по покрытию: подходит она ко
        # всем, а это и есть неоднозначность.
        fits = [
            student_id
            for student_id in set(assigned.values())
            if mine and not (mine & covered(student_id))
        ]
        if page.named:
            near = {
                person.id
                for person, score in scored[page.index][:3]
                if score >= NEAR
            }
            narrowed = [student_id for student_id in fits if student_id in near]
            fits = narrowed or fits

        if len(fits) == 1:
            assigned[page.index] = fits[0]
        else:
            suggest = [person.id for person, score in scored[page.index][:3]]
            offered = fits or suggest
            # мнение модели идёт первым: угадывает она заметно лучше, чем
            # нечёткое сравнение искажённого почерка, но решает всё равно человек
            opinion = guessed(page, roster)
            if opinion:
                offered = [opinion.id] + [one for one in offered if one != opinion.id]
            doubts.append((page.index, offered))

    return assigned, doubts


def troubles(
    page: Page,
    assigned_to: int | None,
    max_mark: int | None,
    questions: int = QUESTIONS,
) -> list[str]:
    """
    Что с этой страницей не так. Список кодов — их показывают человеку.

    Сумма за страницу проверяется, только если она заполнена: ставить её
    необязательно, и пустая клетка не повод для тревоги.

    Не всё в этом списке — беда: часть кодов просто «посмотрите глазами».
    Блокирует разбор один `no_owner`, остальные показываются и пропускаются. А вот балл в клетке,
    которой у этой работы нет вовсе, — повод: клеток на бланке всегда
    пятнадцать, задач бывает меньше, и лишние обязаны остаться пустыми. Это
    бесплатная проверка чтения, и она ловит сдвиг на клетку.
    """
    out = []
    if assigned_to is None:
        out.append("no_owner")
    if not page.named:
        out.append("no_name")
    # Подписана одним именем, без фамилии, — и по этому имени кому-то отдана.
    # Свидетельство тут половинное, а имена повторяются чаще фамилий: на живой
    # пачке страница «Denis» прочиталась как «Misha» и молча ушла Мише, у
    # которого своя страница уже была. Не отказ — пометка: такие показываются
    # человеку всегда, даже когда всё остальное сошлось.
    elif assigned_to is not None and page.first.strip() and not page.surname.strip():
        out.append("first_name_only")
    if any(page.cells[q] is not None for q in range(questions, QUESTIONS)):
        out.append("beyond_questions")
    if max_mark:
        for q in range(questions):
            value = page.cells[q]
            if value is not None and value > max_mark:
                out.append("mark_too_big")
                break
    total = page.page_sum
    if total is not None:
        counted = sum(page.cells[q] for q in page.answered)
        if total != counted:
            out.append("sum_mismatch")
    return out


def merge_marks(pages: list[Page]) -> tuple[dict, list[str]]:
    """
    Баллы одного ученика со всех его страниц в один набор.

    Конфликт — это одна задача с разными баллами на двух страницах: молча
    выбрать одно из двух нельзя, поэтому он называется и идёт человеку.
    """
    marks: dict[int, int] = {}
    conflicts: set[int] = set()
    for page in sorted(pages, key=lambda p: p.index):
        for q in page.answered:
            value = page.cells[q]
            if q in marks and marks[q] != value:
                conflicts.add(q)
            marks[q] = value
    return marks, [f"Q{q + 1}" for q in sorted(conflicts)]
