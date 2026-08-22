"""
Чем план отличается от утверждённого эталона — построчно, а не числами.

Числа («+6 −2») отвечают на вопрос «сильно ли разошлось», но не на вопрос
«что именно вы поменяли», а спрашивают обычно второе — и учитель перед
отправкой, и методист перед решением.

**Сопоставление здесь точное, а не угаданное.** Текстовые инструменты
вроде git ищут соответствие строк по их содержимому и потому вечно
показывают переименование как «удалили и добавили». У нас у каждой строки
есть устойчивый `node_id`: переименованный урок остаётся тем же уроком, и
это видно наверняка.

Единственное место, где нужен приём из текстовых diff'ов, — **порядок**.
Сравнивать позиции в лоб нельзя: вставили урок в начало, и все сто строк
ниже «переехали». Поэтому общая часть двух последовательностей id
считается через LCS, и переехавшими считаются только те строки, которые в
неё не попали.
"""

from typing import NamedTuple, Sequence


class Change(NamedTuple):
    """Строка сравнения: чем она была и чем стала."""

    node_id: int | None
    title: str
    is_section: bool
    state: str  # added | removed | moved | changed | same
    was_title: str = ""
    content_changed: bool = False

    def payload(self) -> dict:
        return {
            "id": self.node_id,
            "title": self.title,
            "is_section": self.is_section,
            "state": self.state,
            "was_title": self.was_title,
            "content_changed": self.content_changed,
        }


def common(before: Sequence[int], after: Sequence[int]) -> list[int]:
    """
    Наибольшая общая подпоследовательность id — то, что осталось на месте.

    Обычная динамика: планов длиннее двух сотен строк не бывает, и
    сорок тысяч ячеек считаются быстрее, чем занимает один запрос к базе.
    """
    rows, columns = len(before), len(after)
    table = [[0] * (columns + 1) for _ in range(rows + 1)]

    for i in range(rows - 1, -1, -1):
        for j in range(columns - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1
                if before[i] == after[j]
                else max(table[i + 1][j], table[i][j + 1])
            )

    result: list[int] = []
    i = j = 0
    while i < rows and j < columns:
        if before[i] == after[j]:
            result.append(before[i])
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1

    return result


def plan_diff(before: Sequence, after: Sequence) -> list[Change]:
    """
    Слить снимок и нынешний план в одну ленту с пометками.

    Удалённые строки остаются на своих прежних местах призраками: сказать
    «удалено 2» мало, надо показать, где они стояли.

    `before` — строки эталона (`PlanBaselineRow`), `after` — нынешний план
    (`services.plan_snapshot`). У обоих есть `node_id`, `title`,
    `is_section` и `content_hash`; у старых снимков отпечатка нет, и тогда
    про содержание мы молчим, а не выдумываем.
    """
    old = {row.node_id: row for row in before if row.node_id}
    new = {row.node_id: row for row in after if row.node_id}
    kept = set(
        common(
            [row.node_id for row in before if row.node_id],
            [row.node_id for row in after if row.node_id],
        )
    )

    changes: list[Change] = []
    index = 0

    def ghosts_until(anchor):
        """Удалённые строки, стоявшие до этого якоря, — на их местах."""
        nonlocal index
        while index < len(before) and before[index].node_id != anchor:
            row = before[index]
            if row.node_id not in new:
                changes.append(
                    Change(row.node_id, row.title, row.is_section, "removed")
                )
            index += 1
        index += 1  # шагнули через сам якорь

    for row in after:
        if row.node_id in kept:
            ghosts_until(row.node_id)

        was = old.get(row.node_id)
        if was is None:
            changes.append(Change(row.node_id, row.title, row.is_section, "added"))
            continue

        # отпечатка нет у тем и у снимков, снятых до того, как его завели
        content = bool(
            getattr(was, "content_hash", "")
            and row.content_hash
            and was.content_hash != row.content_hash
        )
        renamed = was.title != row.title
        state = (
            "moved"
            if row.node_id not in kept
            else "changed"
            if renamed or content
            else "same"
        )
        changes.append(
            Change(
                row.node_id,
                row.title,
                row.is_section,
                state,
                was_title=was.title if renamed else "",
                content_changed=content,
            )
        )

    while index < len(before):
        row = before[index]
        if row.node_id not in new:
            changes.append(Change(row.node_id, row.title, row.is_section, "removed"))
        index += 1

    return changes


def summary(changes: Sequence[Change]) -> dict:
    """Числа по тем же строкам, из которых собрана лента."""
    counted = {"added": 0, "removed": 0, "moved": 0, "changed": 0, "same": 0}
    for change in changes:
        counted[change.state] += 1

    return counted
