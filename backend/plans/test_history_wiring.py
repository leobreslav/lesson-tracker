"""
Сторож журнала: каждый пишущий путь плана снимает снимок.

Потестовый перечень тут не годится — он не поймает эндпоинт, для которого
тест забыли написать вовсе, а забыть здесь значит потерять отмену ровно
там, где она нужнее: на удалении и на импорте `replace`.

Устроен он как сторож очереди записей (`schedule/test_order_wiring.py`) и
по той же причине: правило, которое держится на памяти автора, перестаёт
действовать в первый же занятой день.
"""

import inspect

from django.test import SimpleTestCase
from library import views as library_views

from . import views as plan_views

#: как снимок снимается: через метод вьюсета или напрямую
CALLS = ("self.snapshot(", "history.take(", "plan_history.take(")

#: пути, которые ничего не пишут в план, и потому снимка не требуют
EXCUSED = {
    "PlanNodeViewSet.import_preview": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_rows": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_xlsx": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.baseline_submit": "снимает эталон, план не трогает",
    "PlanNodeViewSet.import_csv": "разбор файла; пишет общий run_import",
    "PlanNodeViewSet.import_rows": "разбор вставки; пишет общий run_import",
    "PlanNodeViewSet.import_xlsx": "разбор книги; пишет общий run_import",
    "PlanTemplateViewSet.from_plan": "заводит новый шаблон, а не правит чужой",
    "PlanTemplateViewSet.keep_updating": "перевешивает пометку, план не трогает",
    "PlanTemplateViewSet.perform_create": "то же заведение, другой конец DRF",
}

WRITING = ("post", "perform_create", "perform_update", "destroy", "perform_destroy")


class HistoryWiringTests(SimpleTestCase):
    def paths(self):
        """Пишущие пути плана: перегрузки, `@action` на запись и APIView."""
        found = {}

        for view in (
            plan_views.PlanNodeViewSet,
            plan_views.SectionMoveView,
            library_views.ImportFromTemplateView,
            # полка пишет **план**: её строки — обычные узлы плана, и
            # обновление с курса способно стереть написанное руками
            library_views.PlanTemplateViewSet,
        ):
            for name in dir(view):
                method = getattr(view, name, None)
                if not callable(method) or name.startswith("__"):
                    continue

                # только своё: у DRF есть свои `perform_destroy` и
                # прочие умолчания, и требовать снимка от чужого кода
                # значит сторожить не то — наш `destroy` их не зовёт
                module = getattr(method, "__module__", "")
                if not module.startswith(("plans", "library", "config")):
                    continue

                writes = name in WRITING or (
                    getattr(method, "mapping", None)
                    and any(
                        verb in method.mapping for verb in ("post", "put", "delete")
                    )
                )
                if writes:
                    found[f"{view.__name__}.{name}"] = inspect.getsource(method)

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
            "путь меняет план мимо журнала — позовите `snapshot()` или "
            "объясните исключение в EXCUSED: без снимка тут пропадает отмена",
        )

    def test_the_excuses_are_still_about_something(self):
        names = self.paths()

        self.assertEqual(
            sorted(name for name in EXCUSED if name not in names),
            [],
            "список исключений не должен переживать удалённые эндпоинты",
        )
