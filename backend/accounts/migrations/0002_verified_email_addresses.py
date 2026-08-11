"""
Заводит подтверждённые EmailAddress для пользователей, созданных до включения
allauth (например, через createsuperuser).

Без этой записи allauth при первом входе через Google считает локальный адрес
неподтверждённым и вызывает wipe_password: пароль становится непригодным и
вход в /admin/ ломается. См. allauth/socialaccount/internal/flows/email_authentication.py
"""
from django.db import migrations


def create_email_addresses(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    for user in User.objects.exclude(email="").iterator():
        email = user.email.lower()
        if EmailAddress.objects.filter(user=user, email__iexact=email).exists():
            continue
        EmailAddress.objects.create(
            user=user,
            email=email,
            verified=True,
            primary=not EmailAddress.objects.filter(user=user, primary=True).exists(),
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("account", "0009_emailaddress_unique_primary_email"),
    ]

    operations = [
        migrations.RunPython(create_email_addresses, noop),
    ]
