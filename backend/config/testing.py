"""
The test runner, and the one thing it exists to guarantee.

**No test ever touches R2.** The rule cannot be left to each test class to
remember: `schools/test_seed_demo.py` runs `seed_demo`, which uploads files,
and it had no idea it was doing so — thirty objects reached the development
bucket before anybody looked. A per-class decorator would have kept missing
exactly the tests that do not think of themselves as file tests.

So the storage is swapped for the whole run, here, once. What is checked with
an in-memory backend is what is actually worth checking — is the object still
there after this, and gone after that. Whether R2 signs a URL correctly is
R2's business and cannot be tested without R2 anyway; that part is verified by
hand against the development bucket.

**И дверь для разработки здесь же закрывается.** На стенде разработки
`E2E_TEST_LOGIN=true` — иначе не войти четырнадцатью учениками без
четырнадцати гугл-аккаунтов. Но сторож двери проверяет ровно обратное: что
при выключенном флаге маршрутов нет вовсе. Если бы он читал окружение, он
проверял бы не код, а `.env` того, кто запустил тесты. Поэтому прогон всегда
идёт с закрытой дверью; браузерному стенду это не мешает — там работает
gunicorn, а не тест-раннер.

**И денег ни один тест не тратит.** Чтение сканов ходит в платный API
Anthropic, а ключ у прогона тот же, что у разработки, — то есть настоящий.
Тест, случайно позвавший `vision.client`, платил бы за каждый запуск, на
каждом шаге работы, и молча: в выводе это выглядит обычным зелёным тестом.
Поэтому ключ на весь прогон пуст, и такой вызов упирается в честный отказ
`ai_key_missing` вместо счёта.

Настоящее чтение этим, разумеется, не проверить — его вообще нельзя
проверить без настоящего запроса. Такой запрос делается руками и только с
разрешения человека; почему именно так — в CLAUDE.md, «Живые запросы к
Anthropic».
"""

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

MEMORY_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
    "files": {
        "BACKEND": "django.core.files.storage.InMemoryStorage",
        "OPTIONS": {"base_url": "/test-files/"},
    },
}


class Runner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._storages = override_settings(STORAGES=MEMORY_STORAGES)
        self._storages.enable()
        # до первого разбора адресов: маршруты двери регистрируются при
        # импорте urls.py, и позже флаг уже ничего не решает
        self._door = override_settings(E2E_TEST_LOGIN=False)
        self._door.enable()
        # Список допущенных — по той же причине, что и дверь выше. У стенда
        # разработки он может стоять в `.env`, и тогда прогон проверял бы не
        # код, а окружение запустившего: половина тестов входа получила бы
        # `not_allowed_here` на ровном месте. Тесты самого списка ставят его
        # себе сами, через `override_settings`.
        self._guest_list = override_settings(LOGIN_ALLOWED_EMAILS=[])
        self._guest_list.enable()
        # платный API: пустой ключ превращает случайный вызов в отказ
        self._purse = override_settings(ANTHROPIC_API_KEY="")
        self._purse.enable()
        # Второй читатель шапки платный так же, и стеречь его надо тем же
        # способом. Отдельное решение тут стоило бы ровно того же, чего стоил
        # первый раз: пустых ключей у Mathpix значит «второго читателя нет», и
        # вызов не случается вовсе.
        self._second_purse = override_settings(MATHPIX_APP_ID="", MATHPIX_APP_KEY="")
        self._second_purse.enable()

    def teardown_test_environment(self, **kwargs):
        self._second_purse.disable()
        self._purse.disable()
        self._guest_list.disable()
        self._door.disable()
        self._storages.disable()
        super().teardown_test_environment(**kwargs)
