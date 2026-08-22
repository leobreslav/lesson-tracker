"""
Сторож у сторожа: проверяет, что `guard-anthropic-spend.py` ловит формы
запуска и **не** ловит текст, который эти формы лишь поминает.

Нужен потому, что портится такое молча и в обе стороны. Перестал ловить —
деньги уходят без вопроса. Начал ловить лишнее — человек привыкает
отмахиваться от вопроса не глядя, и сторож перестаёт работать ровно в тот
раз, когда он прав. Второе уже случилось: правило срабатывало на сообщении
коммита про него самого, дважды за сессию.

Живёт не в наборе Django и не в узловом: `scripts/` не примонтирован ни в
один контейнер — в backend уезжает только `./backend`. Поэтому запускается
прямо, из CI.

Имя файла содержит «guard-anthropic-spend» намеренно: так сама проверка
выведена из-под сторожа и не тревожит человека.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "g", ROOT / "guard-anthropic-spend.py"
)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

SH = "manage.py " + "shell"

ASK = [
    ("прямой запуск в контейнере", f"docker compose exec -T backend python {SH} < probe.py"),
    ("свой исполняемый manage", f"./{SH}"),
    ("curl наружу", "curl -s https://api.anthropic.com/v1/models"),
    ("питон одной строкой", 'docker compose exec -T backend python -c "from vision import client"'),
    ("heredoc, который ИСПОЛНЯЕТСЯ", "python3 - <<'PY'\nfrom vision import client\nclient.read_header(b'')\nPY"),
    ("конструктор клиента в heredoc", "python3 - <<'PY'\nimport anthropic\nc = anthropic.Anthropic(api_key=k)\nPY"),
    ("прямой вызов messages.create", 'python3 -c "c.messages.create(model=m)"'),
]

QUIET = [
    ("сообщение коммита про сторожа",
     f"git commit -q -F - <<'MSG'\nДеньги ушли через отладочный python {SH},\nа не через тест.\nMSG"),
    ("запись файла через heredoc", f"cat > notes.md <<'EOF'\nзапускали python {SH}\nEOF"),
    # Обожглись трижды: правка файла питоном, где в тексте лишь поминается имя
    # переменной. Имя не вызов, и денег оно не стоит.
    ("правка файла, где помянут ключ",
     "python3 - <<'PY'\nt = t.replace('# ANTHROPIC_API' + '_KEY=', 'x')\nopen(p,'w').write(t)\nPY"),
    ("чтение переменной окружения", "docker compose exec -T backend printenv ANTHROPIC_API" + "_KEY"),
    ("подсчёт цены, наружу не ходит", "docker compose exec -T backend python -c 'from vision import prices; print(prices.PRICES)'"),
    ("поиск по коду", "grep -rn 'read_header' backend/"),
    ("обычный прогон тестов", "docker compose exec -T backend python manage.py test"),
    ("чтение исходника", "sed -n '1,20p' backend/vision/client.py"),
    ("браузерные тесты", "./e2e.sh --smoke"),
    ("состояние гита", "git status"),
]

fails = 0
print("── должен спрашивать ──")
for name, cmd in ASK:
    ok = g.verdict(cmd) is not None
    fails += 0 if ok else 1
    print(f"  {'ask   ' if ok else 'ПРОВАЛ'}  {name}")

print("── должен молчать ──")
for name, cmd in QUIET:
    ok = g.verdict(cmd) is None
    fails += 0 if ok else 1
    print(f"  {'молчит' if ok else 'ПРОВАЛ'}  {name}")

print(f"\n  провалов: {fails}")
sys.exit(1 if fails else 0)
