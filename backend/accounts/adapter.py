from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class EmailNotVerifiedError(Exception):
    """Google отдал адрес с email_verified=false."""


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Принимаем только подтверждённые провайдером адреса.

    Иначе allauth не может выполнить auto signup и уводит на HTML-форму
    socialaccount_signup, которой в SPA нет — получается NoReverseMatch и 500.
    Заодно это условие, при котором SOCIALACCOUNT_EMAIL_AUTHENTICATION
    безопасно связывает вход с существующим локальным аккаунтом.
    """

    def pre_social_login(self, request, sociallogin):
        if not any(email.verified for email in sociallogin.email_addresses):
            raise EmailNotVerifiedError
        return super().pre_social_login(request, sociallogin)
