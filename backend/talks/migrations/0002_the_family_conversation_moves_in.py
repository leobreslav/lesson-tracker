"""
Семейная переписка переезжает в общий разговор.

Разговор родителя с учителем был своей таблицей, потому что первым из
разговоров он и появился. Когда собеседников стало трое — коллега, ученик,
родитель, — стало видно, что различается не собеседник, а повод, и три
таблицы под одну вещь означают три пишущих пути и три набора прав. Худшее в
них не объём, а то, что они расходятся **молча**: у сообщения о задаче
отметка о прочтении была, у семейного — нет.

Переезд без потерь и без выдумок: тред становится разговором с поводом
«ребёнок», реплика — сообщением в общей таблице. Порядок в паре
нормализуется по номеру — того требует ограничение новой модели.

Обратный ход написан и работает: он возвращает строки в старые таблицы. Без
него откат миграции унёс бы переписку живой школы.
"""

from django.db import migrations


def move_in(apps, schema_editor):
    Talk = apps.get_model("talks", "Talk")
    Message = apps.get_model("works", "Message")
    FamilyThread = apps.get_model("families", "FamilyThread")

    for thread in FamilyThread.objects.all().iterator():
        lower_id, upper_id = sorted((thread.parent_id, thread.teacher_id))
        # школа берётся у родителя: у обоих она одна, разговор за школу не
        # выходит, и спрашивать её дважды незачем
        school_id = thread.parent.school_id

        talk = Talk.objects.create(
            school_id=school_id,
            lower_id=lower_id,
            upper_id=upper_id,
            child_id=thread.child_id,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )

        for message in thread.messages.all().order_by("created_at", "id"):
            row = Message.objects.create(
                talk=talk,
                author_id=message.author_id,
                # адресат у семейной реплики не хранился: сказанное в тред
                # обращено ко второй стороне, и вычислять её задним числом
                # значило бы выдумать то, чего в базе не было
                to=None,
                text=message.text,
            )
            # `auto_now_add` перебивает переданное время, поэтому час
            # проставляется вторым заходом — иначе вся переписка школы
            # оказалась бы написанной в минуту миграции
            Message.objects.filter(pk=row.pk).update(created_at=message.created_at)


def move_back(apps, schema_editor):
    Talk = apps.get_model("talks", "Talk")
    Message = apps.get_model("works", "Message")
    FamilyThread = apps.get_model("families", "FamilyThread")
    FamilyMessage = apps.get_model("families", "FamilyMessage")
    User = apps.get_model("accounts", "User")

    for talk in Talk.objects.filter(child__isnull=False).iterator():
        sides = User.objects.filter(pk__in=(talk.lower_id, talk.upper_id))
        parent = next((one for one in sides if one.kind == "parent"), None)
        teacher = next((one for one in sides if one.kind == "teacher"), None)
        if parent is None or teacher is None:
            # разговор ученика с учителем о себе в старую таблицу не ложится
            # вовсе: у неё в ключе стоит родитель
            continue

        thread = FamilyThread.objects.create(
            parent=parent,
            teacher=teacher,
            child_id=talk.child_id,
            created_at=talk.created_at,
            updated_at=talk.updated_at,
        )
        for message in Message.objects.filter(talk=talk).order_by("created_at", "id"):
            row = FamilyMessage.objects.create(
                thread=thread, author_id=message.author_id, text=message.text
            )
            FamilyMessage.objects.filter(pk=row.pk).update(
                created_at=message.created_at
            )

    Message.objects.filter(talk__isnull=False).delete()
    Talk.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("talks", "0001_a_talk_is_two_people"),
        ("works", "0034_a_message_belongs_to_a_talk_too"),
        ("families", "0001_initial"),
    ]

    operations = [migrations.RunPython(move_in, move_back)]
