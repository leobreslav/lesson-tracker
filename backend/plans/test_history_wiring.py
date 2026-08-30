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

#: как снимок снимается: через метод вьюсета, напрямую или ходом по ленте.
#:
#: `jump_to` тут потому, что снимает он **сам** — состоянием, из которого
#: уходят, — и снимает ровно один раз за весь ход. Не назвав его, сторож
#: потребовал бы от отмены второго снимка, то есть ровно той беды, ради
#: которой ход и переписан.
CALLS = (
    "self.snapshot(",
    "history.take(",
    "plan_history.take(",
    "history.jump_to(",
)

#: пути, которые ничего не пишут в план, и потому снимка не требуют
EXCUSED = {
    "PlanNodeViewSet.import_preview": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_rows": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.import_preview_xlsx": "предпросмотр ничего не пишет",
    "PlanNodeViewSet.baseline_submit": "снимает эталон, план не трогает",
    "PlanNodeViewSet.import_csv": "разбор файла; пишет общий run_import",
    "PlanNodeViewSet.import_rows": "разбор вставки; пишет общий run_import",
    "PlanNodeViewSet.import_xlsx": "разбор книги; пишет общий run_import",
    "PlanNodeViewSet.redo": (
        "ход вперёд по ленте: состояние уже записано, снимать нечего — "
        "а снятый снимок сделал бы возврат новым действием и вернул бы "
        "«отменить отмену»"
    ),
    "PlanTemplateViewSet.from_plan": "заводит новый шаблон, а не правит чужой",
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


class SnapshotsSitInsideTheWriteTransactionTests(SimpleTestCase):
    """
    Снимок снимается внутри той же транзакции, что и сама запись.

    Порядок «снимок, потом правка» обязателен: снимок отвечает на «как
    было». Но у `history.take` свой атомарный блок, и вызванный **снаружи**
    транзакции записи он коммитится сам по себе — то есть переживает отказ,
    случившийся ниже. Правка не состоялась, а шаг в журнале появился.

    Бед от этого три. Кнопка отмены предлагает отменить действие, которого
    не было, и, нажатая, отменяет предыдущее настоящее. Пустые шаги
    вытесняют настоящие из двадцати, что держит `prune`. И если правку
    пробовал не ведущий курса, снимок ложится «вмешательством»: живёт
    девяносто дней и показывается учителю пометкой о чужой правке, которой
    не было.

    Проверяется текстом, а не поведением, и намеренно. Поведение проверено
    отдельно (`ARefusedEditLeavesNoStepTests`), но потестовый перечень
    закрывает те пути, до которых у кого-то дошли руки: отказов у плана
    больше десятка, и заводить тест на каждое сочетание «путь × отказ»
    никто не станет. Здесь же вопрос один и на все пути сразу — стоит ли
    вызов под открытой транзакцией.
    """

    #: где живут пишущие пути плана
    SOURCES = ("plans/views.py", "library/views.py")

    #: у этого метода `history.take` в теле — не вызов, а определение
    HELPER = "snapshot"

    def offenders(self) -> list:
        """Вызовы снимка, над которыми нет открытого `transaction.atomic()`."""
        from pathlib import Path

        from django.conf import settings

        found = []
        for name in self.SOURCES:
            lines = (
                (Path(settings.BASE_DIR) / name).read_text(encoding="utf-8").splitlines()
            )
            #: отступы открытых блоков транзакции, стопкой
            blocks, method = [], ""

            for number, line in enumerate(lines, 1):
                body = line.strip()
                if not body or body.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())

                # блок закрылся, как только строка вернулась на его уровень
                while blocks and indent <= blocks[-1]:
                    blocks.pop()

                if body.startswith("def "):
                    method = body[4:].split("(")[0]
                if body.startswith("with transaction.atomic()"):
                    blocks.append(indent)
                    continue

                if method != self.HELPER and any(call in body for call in CALLS):
                    if not blocks:
                        found.append(f"{name}:{number}")

        return found

    def test_no_snapshot_is_taken_outside_a_transaction(self):
        self.assertEqual(
            self.offenders(),
            [],
            "снимок снимается вне транзакции записи: отказ ниже его не "
            "унесёт, и в журнале останется шаг, которого не было. "
            "Заведите `with transaction.atomic():` вокруг снимка и правки",
        )

    def test_the_check_would_notice_a_snapshot_left_outside(self):
        """
        Сторож умеет сказать «нет» — проверено на выдуманном исходнике.

        Сторож, у которого не бывает отказа, неотличим от неработающего, а
        текстовая проверка ошибается молча: достаточно опечатки в имени
        блока, и она разрешит всё подряд.
        """
        source = [
            "    def destroy(self, request):",
            "        self.snapshot(node.owner, 'delete', node.title)",
            "",
            "        with transaction.atomic():",
            "            node.delete()",
        ]

        blocks, caught = [], []
        for number, line in enumerate(source, 1):
            body = line.strip()
            if not body:
                continue
            indent = len(line) - len(line.lstrip())
            while blocks and indent <= blocks[-1]:
                blocks.pop()
            if body.startswith("with transaction.atomic()"):
                blocks.append(indent)
                continue
            if any(call in body for call in CALLS) and not blocks:
                caught.append(number)

        self.assertEqual(caught, [2], "разбор обязан ловить снимок перед блоком")
