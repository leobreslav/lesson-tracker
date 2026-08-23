from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.test import override_settings
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


@override_settings(LOGIN_ALLOWED_EMAILS=["me@example.com"])
class AllowedAddressesTests(APITestCase):
    """
    Контур со списком допущенных пускает только их — обеими дверями.

    Список нужен контуру, у которого своей публики нет: стенду. У прода
    список пуст, допуск даёт приглашение школы, и всё это правило для него —
    пустая проверка.

    Дверей две, и вторая опаснее первой. `/api/auth/google/` хотя бы требует
    настоящего аккаунта Google; `/api/test/login/` выдаёт токен **кому угодно
    по адресу** — она для браузерных тестов и живёт за флагом. Пока стенд был
    закрыт паролем nginx, снаружи её было не достать; пароля больше нет.
    Правило, написанное только у первой двери, оставило бы вторую открытой, и
    выглядело бы это как «контур закрыт», пока кто-нибудь не наберёт второй
    адрес.
    """

    def test_a_stranger_is_refused_at_the_google_door(self):
        response = google_login({"email": "somebody@example.com"})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "not_allowed_here")

    def test_the_refused_stranger_leaves_no_account_behind(self):
        """
        Отказ идёт до авторегистрации, а не после.

        Иначе каждый чужой вход оставлял бы заготовку пользователя, и убирать
        их пришлось бы руками — а список бы всё равно не пустил.
        """
        google_login({"email": "somebody@example.com"})

        self.assertFalse(User.objects.filter(email="somebody@example.com").exists())

    def test_the_allowed_address_gets_in(self):
        response = google_login({"email": "me@example.com"})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(User.objects.filter(email="me@example.com").exists())

    @override_settings(LOGIN_ALLOWED_EMAILS=["Me@Example.COM"])
    def test_the_case_of_the_address_does_not_matter(self):
        """Адрес пишут как придётся, а Google отдаёт канонический."""
        self.assertEqual(google_login({"email": "me@example.com"}).status_code, 200)

    @override_settings(LOGIN_ALLOWED_EMAILS=[])
    def test_an_empty_list_admits_everybody(self):
        """Прод: список пуст, и правило не действует вовсе."""
        self.assertEqual(
            google_login({"email": "somebody@example.com"}).status_code, 200
        )


@override_settings(E2E_TEST_LOGIN=True, LOGIN_ALLOWED_EMAILS=["me@example.com"])
class DevDoorAsksWhoIsKnockingTests(APITestCase):
    """
    Дев-дверь на контуре со списком требует токен допущенного.

    Вьюхи зовутся напрямую: маршруты добавляются в таблицу по флагу в момент
    импорта, и `override_settings` их туда уже не добавит. Проверять всё
    равно надо саму вьюху — замок стоит в ней, а не в маршрутизации.
    """

    def setUp(self):
        self.owner = User.objects.create_user(email="me@example.com")
        self.somebody = User.objects.create_user(email="somebody@example.com")
        self.factory = APIRequestFactory()

    def knock(self, view, *, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Token {token}"} if token else {}
        request = self.factory.post("/", {"email": "somebody@example.com"}, **headers)
        return view.as_view()(request)

    def test_without_a_token_the_door_refuses(self):
        from accounts.e2e import TestLoginView

        response = self.knock(TestLoginView)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "not_allowed_here")

    def test_a_token_of_somebody_else_does_not_open_it(self):
        """
        Подменившийся ученическим токеном обратно этой дверью не ходит.

        Отсюда правило на клиенте: переключатель «войти как» стучится
        **домашним** токеном (`devSwitch.homeToken`). Спроси он текущий —
        подмена работала бы ровно один раз.
        """
        from accounts.e2e import TestLoginView

        key = Token.objects.create(user=self.somebody).key

        self.assertEqual(self.knock(TestLoginView, token=key).status_code, 403)

    def test_the_owner_of_the_contour_walks_in(self):
        from accounts.e2e import TestLoginView

        key = Token.objects.create(user=self.owner).key
        response = self.knock(TestLoginView, token=key)

        self.assertEqual(response.status_code, 200, response.data)

    def test_the_list_of_people_is_closed_too(self):
        """Список людей — это перечень адресов школы, и он не для всех."""
        from accounts.e2e import TestPeopleView

        response = TestPeopleView.as_view()(self.factory.get("/"))

        self.assertEqual(response.status_code, 403)

    def test_the_reset_is_closed_too(self):
        """А эта дверь сносит базу целиком."""
        from accounts.e2e import TestResetView

        response = TestResetView.as_view()(self.factory.post("/"))

        self.assertEqual(response.status_code, 403)

    @override_settings(LOGIN_ALLOWED_EMAILS=[])
    def test_without_a_list_the_door_stays_as_it_was(self):
        """
        Контур браузерных тестов: списка нет, и дверь открыта, как была.

        Без этого набор `e2e` перестал бы входить вовсе — он стучится сюда до
        того, как у него появился хоть какой-нибудь токен.
        """
        from accounts.e2e import TestPeopleView

        response = TestPeopleView.as_view()(self.factory.get("/"))

        self.assertEqual(response.status_code, 200)
