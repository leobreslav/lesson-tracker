from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import authenticate, get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

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
        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )

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

    def test_logout_deletes_token(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.assertEqual(self.client.post(reverse("rest_logout")).status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.user).exists())
