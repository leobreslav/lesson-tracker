"""
Сторож журнала расписания: каждый пишущий путь снимает снимок.

Потестовый перечень тут не годится — он не поймает эндпоинт, для которого
тест забыли написать вовсе, а забыть здесь значит потерять отмену ровно
там, где она нужнее: на массовой уборке и на копировании периода.

Устроен он как сторож очереди записей (`schedule/test_order_wiring.py`) и
сторож журнала плана (`plans/test_history_wiring.py`) — то же правило, тот
же вид, и это нарочно: три разных способа проверить одно и то же разошлись
бы при первой же правке.
"""

import inspect

from django.test import SimpleTestCase

from . import views as slot_views

#: как выглядит «путь снял снимок»
CALLS = ("self.snapshot(", "self.snapshot_all(", "history.take(")

#: пути, которые расписания не меняют, и потому снимка не требуют
EXCUSED = {
    "SlotViewSet.attendance": (
        "журнал посещаемости висит на занятии, а не двигает его: сетка после "
        "отметки та же. Отмена журнала — отдельный разговор и своя кнопка"
    ),
    "SlotViewSet.slot_undo": (
        "сама отмена снимок снимает, но своим путём: он должен лечь до "
        "восстановления и по всем курсам партии сразу"
    ),
}

WRITING = ("perform_create", "perform_update", "perform_destroy", "destroy")


class ScheduleHistoryWiringTests(SimpleTestCase):
    def paths(self):
        """Пишущие пути расписания: перегрузки и `@action` на запись."""
        found = {}

        for name, member in vars(slot_views.SlotViewSet).items():
            if not callable(member) or name.startswith("__"):
                continue

            writes = name in WRITING or bool(
                set(getattr(member, "mapping", {}) or {})
                & {"post", "put", "patch", "delete"}
            )
            if writes:
                found[f"SlotViewSet.{name}"] = inspect.getsource(member)

        return found

    def test_every_write_path_takes_a_snapshot(self):
        missing = sorted(
            name
            for name, source in self.paths().items()
            if name not in EXCUSED and not any(call in source for call in CALLS)
        )

        self.assertEqual(
            missing,
            [],
            "путь меняет расписание мимо журнала — позовите `snapshot()` или "
            "объясните исключение в EXCUSED: без снимка тут пропадает отмена",
        )

    def test_the_excuses_are_still_about_something(self):
        """Список исключений не должен переживать удалённые эндпоинты."""
        names = self.paths()

        self.assertEqual(
            sorted(name for name in EXCUSED if name not in names),
            [],
            "исключение объясняет путь, которого больше нет",
        )


class SnapshotCoversTheSlotTests(SimpleTestCase):
    """
    Сторож устройства: снимок обязан знать про **всё**, что есть у занятия.

    Пишущие пути стережёт сторож выше, но у отмены есть вторая половина, и
    она страшнее: путь на месте, снимок снимается, а поле, добавленное
    занятию в прошлом месяце, в нём не лежит — и отмена молча возвращает
    клетку без него. Ни один тест поведения этого не поймает: он проверяет
    то, что было, когда его писали.

    Поэтому список полей перечислен здесь, и незнакомое роняет тест с
    требованием **решить**: это состояние занятия (в снимок) или нет (в
    исключения, с причиной). Тот же приём, что у реестра сквозных правил.
    """

    #: поля занятия, которых в снимке нет намеренно
    FIELDS_EXCUSED = {
        "id": "сам ключ: по нему клетка и воскресает",
        "year": "равен году курса; снимок, умеющий его переписать, выражал бы "
        "состояние, которого не допускает сериализатор",
        "course": "единица снимка — курс целиком, в строке его повторять нечем",
        "created_at": "когда клетку завели; воскрешённая заводится заново, и "
        "врать об этом хуже, чем потерять",
        "snapshot_rows": "строки журнала не поле занятия, а ссылка на него",
    }

    #: что висит на занятии и уходит вместе с ним
    RELATED_EXCUSED = {}

    def test_every_field_of_a_slot_is_either_restored_or_excused(self):
        from .history import ROW_FIELDS
        from .models import Slot

        kept = set(ROW_FIELDS) | {f"{name}_id" for name in ROW_FIELDS}
        unknown = sorted(
            field.name
            for field in Slot._meta.get_fields()
            if not field.is_relation or not field.auto_created
            if field.name not in self.FIELDS_EXCUSED
            and field.name not in kept
            and f"{field.name}_id" not in kept
        )

        self.assertEqual(
            unknown,
            [],
            "у занятия появилось поле, которого нет в снимке: решите, это его "
            "состояние (тогда в ROW_FIELDS) или нет (тогда в FIELDS_EXCUSED "
            "с причиной) — иначе отмена вернёт клетку без него",
        )

    def test_everything_hanging_on_a_slot_is_either_kept_or_excused(self):
        """
        Связи на занятие: посещаемость уходит каскадом, работы — по SET_NULL.

        Третья такая связь появится, и заметить это надо в тот день, а не
        когда человек нажмёт «Отменить» и не досчитается своей работы.
        """
        from .models import Slot

        kept = {"attendance", "works"}
        found = sorted(
            rel.get_accessor_name()
            for rel in Slot._meta.related_objects
            # журнал ссылается на занятие числом, а не связью: он и должен
            # пережить его удаление
            if rel.related_model.__name__ not in ("SlotSnapshotRow",)
        )

        unknown = [name for name in found if name not in kept | set(self.RELATED_EXCUSED)]

        self.assertEqual(
            unknown,
            [],
            "на занятие сослались чем-то новым: решите, возвращает ли это "
            "отмена (тогда в снимок, как посещаемость) или нет (тогда в "
            "RELATED_EXCUSED с причиной)",
        )
