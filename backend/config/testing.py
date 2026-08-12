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

    def teardown_test_environment(self, **kwargs):
        self._storages.disable()
        super().teardown_test_environment(**kwargs)
