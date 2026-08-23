from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .door import refuse_unless_allowed


class EmailNotVerifiedError(Exception):
    """Google returned the address with email_verified=false."""


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Only addresses the provider verified are accepted.

    Otherwise allauth cannot auto-signup and redirects to the HTML form
    socialaccount_signup, which an SPA does not have — that gives a
    NoReverseMatch and a 500. It is also the condition under which
    SOCIALACCOUNT_EMAIL_AUTHENTICATION safely links a sign-in to an existing
    local account, and the condition invitations rely on: an unverified
    address must never be enough to walk into a school.
    """

    def pre_social_login(self, request, sociallogin):
        if not any(email.verified for email in sociallogin.email_addresses):
            raise EmailNotVerifiedError

        # Список допущенных спрашивается здесь, а не в сериализаторе, и это
        # выбор: `pre_social_login` идёт **до** авторегистрации, поэтому
        # отказ не оставляет за собой заведённого пользователя. Проверка
        # после входа означала бы, что чужой в базе уже есть, — и убирать его
        # пришлось бы руками. Адрес берём у провайдера, а не из тела запроса:
        # своим он назваться не может.
        refuse_unless_allowed(sociallogin.user.email)

        return super().pre_social_login(request, sociallogin)
