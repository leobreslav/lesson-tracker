"""
Сторож над самим исходником: одно имя — одно определение.

Правка однажды приложилась дважды, и это прошло молча: в
`schools/serializers.py` оказалось **два** `MemberSerializer` и два
`InvitationSerializer`, а в `SlotViewSet` — два `perform_destroy`. Питон в
таком случае не жалуется, а просто оставляет последнее определение, поэтому
беда тихая вдвойне: тесты зелёные, поведение то самое, а половина файла —
мёртвый код, который следующий читатель откроет и станет править. Правил он
бы при этом копию, которая не работает.

Ни один тест этого не поймает по существу: он проверяет поведение, а
поведение у победившей копии правильное. Ловится это только взглядом на
текст, а взгляд забывают — значит нужен сторож.

Проверка дешёвая (разбор всех модулей — доли секунды) и покрывает весь
backend сразу, включая тот код, для которого тестов ещё нет.
"""

import ast
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

#: миграции пропускаем: там встречаются одноимённые вложенные объекты, и
#: правит их не человек
SKIP = {"migrations"}

DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def modules():
    root = Path(__file__).resolve().parent.parent
    for path in sorted(root.rglob("*.py")):
        if SKIP & set(path.parts):
            continue
        yield path.relative_to(root), ast.parse(path.read_text(encoding="utf-8"))


def duplicates(names):
    return sorted(name for name, count in Counter(names).items() if count > 1)


class DuplicateDefinitionTests(SimpleTestCase):
    def test_a_module_defines_each_name_once(self):
        for path, tree in modules():
            with self.subTest(module=str(path)):
                found = duplicates(
                    node.name for node in tree.body if isinstance(node, DEFINITIONS)
                )
                self.assertEqual(
                    found,
                    [],
                    f"{path}: определено дважды — {found}. "
                    "Питон оставит последнее, а первое станет мёртвым кодом, "
                    "который однажды поправят вместо живого.",
                )

    def test_a_class_defines_each_method_once(self):
        for path, tree in modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                with self.subTest(module=str(path), cls=node.name):
                    found = duplicates(
                        item.name for item in node.body if isinstance(item, DEFINITIONS)
                    )
                    self.assertEqual(
                        found,
                        [],
                        f"{path}: у {node.name} дважды объявлено {found}. "
                        "Работать будет последнее объявление.",
                    )
