from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIRequestFactory, APITestCase

User = get_user_model()

# claims, которые Google кладёт в id_token; подпись в тестах не проверяем
GOOGLE_CLAIMS = {
    "iss": "https://accounts.google.com",
    "sub": "1234567890",
    "email": "teacher@example.com",
    "email_verified": True,
    "given_name": "Мария",
    "family_name": "Иванова",
}


def google_login(claims=None):
    """Подменяет проверку подписи id_token и возвращает ответ эндпоинта."""
    target = "allauth.socialaccount.providers.google.views._verify_and_decode"
    with patch(target, return_value={**GOOGLE_CLAIMS, **(claims or {})}):
        from django.test import Client

        return Client().post(
            reverse("google_login"),
            {"id_token": "fake"},
            content_type="application/json",
        )


class GoogleLoginTests(APITestCase):
    def test_creates_user_on_first_login(self):
        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("key", response.json())

        user = User.objects.get(email="teacher@example.com")
        self.assertEqual(user.first_name, "Мария")
        self.assertEqual(Token.objects.get(user=user).key, response.json()["key"])

    def test_second_login_reuses_same_user(self):
        google_login()
        google_login()

        self.assertEqual(User.objects.filter(email="teacher@example.com").count(), 1)

    def test_links_to_existing_account_and_keeps_password(self):
        """SOCIALACCOUNT_EMAIL_AUTHENTICATION: вход подхватывает локальный аккаунт."""
        user = User.objects.create_user(
            email="teacher@example.com", password="S3cret-pass-123"
        )
        # create_user marks the address verified itself — see UserManager

        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(SocialAccount.objects.filter(user=user).exists())

        # пароль не должен быть затёрт — иначе ломается вход в /admin/
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())
        self.assertIsNotNone(
            authenticate(username="teacher@example.com", password="S3cret-pass-123")
        )

    def test_fills_empty_name_of_existing_account(self):
        """Аккаунт, заведённый без имени, получает его из Google при входе."""
        user = User.objects.create_user(
            email="teacher@example.com", password="S3cret-pass-123"
        )
        # create_user marks the address verified itself — see UserManager

        google_login()

        user.refresh_from_db()
        self.assertEqual(user.first_name, "Мария")
        self.assertEqual(user.last_name, "Иванова")

    def test_does_not_overwrite_edited_name(self):
        """Отредактированное в профиле имя вход через Google не затирает."""
        user = User.objects.create_user(
            email="teacher@example.com",
            password="S3cret-pass-123",
            first_name="Маша",
            last_name="Петрова",
        )
        # create_user marks the address verified itself — see UserManager

        google_login()

        user.refresh_from_db()
        self.assertEqual(user.first_name, "Маша")
        self.assertEqual(user.last_name, "Петрова")

    def test_unverified_email_does_not_hijack_account(self):
        """Неподтверждённый в Google адрес не должен давать доступ к чужому аккаунту."""
        User.objects.create_user(email="teacher@example.com", password="S3cret-pass-123")

        response = google_login({"email_verified": False})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(SocialAccount.objects.count(), 0)

    def test_invalid_token_returns_400(self):
        response = self.client.post(
            reverse("google_login"), {"id_token": "garbage"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_token_returns_400(self):
        response = self.client.post(reverse("google_login"), {}, format="json")

        self.assertEqual(response.status_code, 400)


class MeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="teacher@example.com", password="S3cret-pass-123", first_name="Мария"
        )
        self.token = Token.objects.create(user=self.user)

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_returns_current_user(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.get(reverse("me"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "teacher@example.com")
        self.assertEqual(response.json()["first_name"], "Мария")

    def test_patch_updates_name(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.patch(
            reverse("me"), {"first_name": "Мария", "last_name": "Иванова"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Мария")
        self.assertEqual(self.user.last_name, "Иванова")

    def test_patch_accepts_single_field(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.patch(
            reverse("me"), {"last_name": "Иванова"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Мария")  # не затёрлось
        self.assertEqual(self.user.last_name, "Иванова")

    def test_patch_ignores_email(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.patch(
            reverse("me"), {"email": "hacker@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "teacher@example.com")

    def test_patch_requires_authentication(self):
        response = self.client.patch(
            reverse("me"), {"first_name": "Кто-то"}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    def test_patch_touches_only_own_profile(self):
        other = User.objects.create_user(
            email="other@example.com", password="S3cret-pass-123", first_name="Пётр"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.client.patch(reverse("me"), {"first_name": "Мария II"}, format="json")

        other.refresh_from_db()
        self.assertEqual(other.first_name, "Пётр")

    def test_put_not_allowed(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.put(
            reverse("me"), {"first_name": "Мария"}, format="json"
        )

        self.assertEqual(response.status_code, 405)

    def test_language_defaults_to_english(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.assertEqual(self.client.get(reverse("me")).json()["language"], "en")

    def test_language_can_be_changed(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.patch(reverse("me"), {"language": "ru"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, "ru")

    def test_unknown_language_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.patch(reverse("me"), {"language": "kl"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, "en")

    def test_logout_deletes_token(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.assertEqual(self.client.post(reverse("rest_logout")).status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.user).exists())


class E2EDoorTests(APITestCase):
    """
    The browser-test door must be shut unless the environment opens it.

    Checked as a routing fact rather than a permission one: with the flag
    off the path is not registered at all, so `reverse` cannot even name it.
    """

    def test_the_routes_do_not_exist_by_default(self):
        from django.urls import NoReverseMatch, reverse

        self.assertFalse(settings.E2E_TEST_LOGIN, "флаг не должен быть включён")

        for name in ("e2e-login", "e2e-people", "e2e-reset"):
            with self.subTest(name), self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_the_paths_answer_404(self):
        for path in ("/api/test/login/", "/api/test/reset/"):
            with self.subTest(path):
                self.assertEqual(self.client.post(path).status_code, 404)

        # список людей закрыт так же: он говорит, кто есть в базе, и в
        # чужих руках это готовый перечень адресов школы
        self.assertEqual(self.client.get("/api/test/people/").status_code, 404)

    def test_the_view_refuses_even_if_wired_by_hand(self):
        """
        A second lock: the check is in the view, not only in the routing.

        DRF turns the Http404 into a response rather than letting it fly, so
        the status is what there is to look at.
        """
        from accounts.e2e import TestLoginView, TestPeopleView

        request = APIRequestFactory().post("/", {"email": "teacher@example.com"})

        response = TestLoginView.as_view()(request)
        listing = TestPeopleView.as_view()(APIRequestFactory().get("/"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(listing.status_code, 404)
