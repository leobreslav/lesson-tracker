"""
Сторож поверх правила очереди, а не поверх отдельных запретов.

Девять дыр появились одинаково: писали мимо проверки, а не вопреки ей.
Перечислять их поимённо в тестах мало — новый эндпоинт в такой список
никто не обязан добавлять. Поэтому проверяется устройство: **каждый**
пишущий путь к занятиям и плану либо зовёт общую проверку, либо стоит
здесь в списке с причиной.

Причина обязательна и пишется словами: список без объяснений через
полгода нельзя ни починить, ни выбросить.
"""

import inspect

from django.test import SimpleTestCase
from plans import views as plan_views
from schedule import views as slot_views

# как выглядит «путь проверяет очередь»: либо общее пост-условие, либо
# сериализатор занятия, который несёт все правила записи
GUARDS = (
    "guard_order",
    "refuse_if_records_broken",
    "refuse_if_taught_lost",
    "refuse_if_taught",
    "refuse_if_before_taught",
    "refuse_if_deleting_taught",
    "SlotSerializer",
    "broken_record",
    # действие может и делегировать: проверка стоит в общем помощнике
    "run_import",
    "perform_move",
)

EXCUSED = {
    "SlotViewSet.bulk": "массовое удаление сносит только пустые клетки (sweepable)",
    "SlotViewSet.attendance": "журнал посещаемости связи не касается",
    "SlotViewSet.perform_destroy": "удаление записанного отклоняется по своему коду",
    "PlanNodeViewSet.destroy": "удаление проведённой строки отклоняется по своему коду",
    "PlanNodeViewSet.import_preview": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_rows": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_xlsx": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.baseline_submit": "снимок плана ничего в нём не меняет",
}


def written_by(view, names):
    """Исходники методов, которые пишут: остальные нас не интересуют."""
    for name in names:
        method = getattr(view, name, None)
        if method is not None:
            yield f"{view.__name__}.{name}", inspect.getsource(method)


class OrderWiringTests(SimpleTestCase):
    def paths(self):
        """Пишущие пути обоих вьюсетов: перегрузки и @action на запись."""
        found = []

        for view in (slot_views.SlotViewSet, plan_views.PlanNodeViewSet):
            names = [
                name
                for name, member in vars(view).items()
                if callable(member)
                and (
                    name.startswith("perform_")
                    or name == "destroy"
                    or set(getattr(member, "mapping", {}) or {})
                    & {"post", "patch", "put", "delete"}
                )
            ]
            found.extend(written_by(view, names))

        return found

    def test_every_write_path_asks_about_the_queue(self):
        unguarded = [
            name
            for name, source in self.paths()
            if name not in EXCUSED and not any(guard in source for guard in GUARDS)
        ]

        self.assertEqual(
            unguarded,
            [],
            "путь пишет мимо проверки очереди — позовите `guard_order` или "
            "объясните исключение в EXCUSED",
        )

    def test_the_excuses_are_still_about_something(self):
        """Список исключений не должен переживать удалённые эндпоинты."""
        names = {name for name, _ in self.paths()}

        self.assertEqual([name for name in EXCUSED if name not in names], [])
