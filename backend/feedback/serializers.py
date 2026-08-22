from rest_framework import serializers

from .models import Message


class MessageSerializer(serializers.ModelSerializer):
    """
    Обращение с обеих сторон одним сериализатором.

    Пишущему видны два поля — вид и текст, — всё остальное он не сообщает, а
    оно **узнаётся**: кто, из какой школы, с какой страницы, когда. Спрашивать
    это у человека значило бы просить его пересказать то, что мы и так знаем,
    а на пересказе ошибаются: «у меня не работает журнал» с адресом страницы
    и без — это два разных сообщения по стоимости разбора.
    """

    author_name = serializers.SerializerMethodField()
    author_email = serializers.EmailField(source="author.email", read_only=True)
    school_name = serializers.CharField(source="school.name", read_only=True)

    class Meta:
        model = Message
        fields = (
            "id",
            "kind",
            "text",
            "page",
            "author",
            "author_name",
            "author_email",
            "school",
            "school_name",
            "created_at",
            "handled_at",
        )
        read_only_fields = (
            "id",
            "author",
            "author_name",
            "author_email",
            "school",
            "school_name",
            "created_at",
        )

    def get_author_name(self, message) -> str:
        # имя собирается тут, а не общим помощником: `full_name` в проекте
        # уже трижды свой, и четвёртая копия ради одной строки — плохая цена
        # за красоту. Ушедший автор имени не имеет вовсе, и врать про него нечем
        if not message.author_id:
            return ""
        person = message.author
        return " ".join(filter(None, (person.first_name, person.last_name)))

    def validate_text(self, value):
        text = (value or "").strip()
        if not text:
            raise serializers.ValidationError("Write what happened.")
        return text
