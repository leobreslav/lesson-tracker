"""
Приглашение перестаёт ждать первого входа и заводит учётку.

Существующие неиспользованные приглашения превращаются в людей: строка
`User` со школой, видом и ролью, а курсы, которые приглашение носило,
раздаются обычными таблицами — ученика зачисляем, учителю поручаем вести.
После этого поле `courses` у приглашения не значит ничего и уходит.

Занятый курс при переносе пропускается молча: ведущий у курса один, и
решение администратора, сделанное позже, важнее пожелтевшего приглашения.
Логика тут своя, а не из `services`: миграция обязана работать на том коде,
каким он был в момент её написания.
"""

from django.db import migrations, models


def provision_pending(apps, schema_editor):
    Invitation = apps.get_model("schools", "Invitation")
    User = apps.get_model("accounts", "User")
    CourseStudent = apps.get_model("schedule", "CourseStudent")
    CourseAssignment = apps.get_model("schedule", "CourseAssignment")

    pending = Invitation.objects.filter(accepted_at__isnull=True).prefetch_related(
        "courses"
    )

    for invitation in pending:
        email = invitation.email.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            continue

        person = User.objects.create(
            email=email,
            school_id=invitation.school_id,
            kind=invitation.kind,
            is_school_admin=invitation.is_school_admin,
            first_name=(invitation.name or "")[:150],
            password="!",  # непригодный, как у set_unusable_password
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )

        for course in invitation.courses.all():
            if invitation.kind == "student":
                CourseStudent.objects.get_or_create(
                    course=course,
                    student=person,
                    defaults={"added_by_id": invitation.created_by_id},
                )
            elif not CourseAssignment.objects.filter(course=course).exists():
                CourseAssignment.objects.create(course=course, teacher=person)


class Migration(migrations.Migration):

    dependencies = [
        ("schools", "0006_alter_invitation_courses"),
        ("schedule", "0016_attendance"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(provision_pending, migrations.RunPython.noop),
        migrations.RemoveField(model_name="invitation", name="courses"),
    ]
