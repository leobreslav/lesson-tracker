from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """User manager keyed by email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        self._mark_email_verified(user)
        return user

    @staticmethod
    def _mark_email_verified(user):
        """
        Give an account made from the command line a verified address.

        Without it, allauth's email authentication calls `wipe_password` on
        the first Google sign-in and the freshly created superuser loses the
        password to /admin/. Accounts made this way are trusted by
        construction — somebody with shell access typed them in.

        Only the manager does this. allauth builds its users directly and
        asserts that no EmailAddress exists yet, so hooking post_save here
        would break signing up through Google.
        """
        from allauth.account.models import EmailAddress

        EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={"verified": True, "primary": True},
        )

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True")

        return self._create_user(email, password, **extra_fields)


class Kind(models.TextChoices):
    """
    Учитель или ученик. Второй вид пользователя, а не роль внутри первого.

    Роль (`is_school_admin`) — это права над общими объектами школы у того же
    учителя; переключаться между ролями не нужно, интерфейс один. Ученик —
    другое дело: у него другой интерфейс целиком, он не должен видеть ни
    расписания, ни планов, поэтому ветвление идёт на входе, а не внутри
    экранов.

    Вид проставляется один раз, при приёме приглашения, и не меняется:
    один адрес — либо учитель, либо ученик. Учительскую и ученическую
    учётку на одной почте держать нельзя, и это проверяется при
    приглашении, а не при входе.
    """

    TEACHER = "teacher", "teacher"
    STUDENT = "student", "student"


class Language(models.TextChoices):
    """UI languages. English is the default; the value is a plain ISO code."""

    EN = "en", "English"
    RU = "ru", "Русский"


class User(AbstractUser):
    """
    A teacher, and possibly an administrator of their school — or a student.

    One user belongs to one school: a teacher working in two places would need
    two accounts, and that is a fair trade for keeping every query scoped by a
    single foreign key.

    The roles are not exclusive and there is no mode to switch: an
    administrator is a teacher with extra rights over the school's shared
    objects — the calendar and the list of courses.

    `school` stays nullable because a signed-in user without a school is a
    real state: Google let them in, but nobody has invited them yet.

    `kind` делит пользователей на два интерфейса. Принадлежность школе
    перестала означать «сотрудник»: ученик тоже в школе, и каждое место,
    где выборка «люди школы» подразумевала учителей, сужено явно.
    """

    Kind = Kind

    username = None
    email = models.EmailField(_("email address"), unique=True)
    kind = models.CharField(
        "kind",
        max_length=8,
        choices=Kind,
        default=Kind.TEACHER,
        help_text="Учитель или ученик: у них разные интерфейсы целиком.",
    )
    language = models.CharField(
        _("interface language"),
        max_length=5,
        choices=Language,
        default=Language.EN,
    )
    school = models.ForeignKey(
        "schools.School",
        related_name="members",
        null=True,
        blank=True,
        # PROTECT: a school with people in it must not disappear by accident,
        # and deleting it would silently orphan its calendar and courses
        on_delete=models.PROTECT,
        verbose_name="school",
    )
    is_school_admin = models.BooleanField("school administrator", default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def is_student(self) -> bool:
        return self.kind == Kind.STUDENT

    def __str__(self):
        return self.email
