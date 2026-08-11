from allauth.account.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def fill_name_from_google(sender, request, user, sociallogin=None, **kwargs):
    """
    Подставляет имя и фамилию из Google, если они пустые.

    При регистрации нового пользователя allauth заполняет их сам, но по
    существующему аккаунту (созданному через createsuperuser или найденному
    по email) регистрация не выполняется, и поля остаются пустыми.

    Уже заполненные значения не трогаем: пользователь мог отредактировать
    их в профиле, и вход через Google не должен это затирать.
    """
    if sociallogin is None:
        return

    data = sociallogin.account.extra_data
    updated = []

    if not user.first_name and data.get("given_name"):
        user.first_name = data["given_name"][:150]
        updated.append("first_name")

    if not user.last_name and data.get("family_name"):
        user.last_name = data["family_name"][:150]
        updated.append("last_name")

    if updated:
        user.save(update_fields=updated)
