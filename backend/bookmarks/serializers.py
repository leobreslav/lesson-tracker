from config.errors import Codes, api_error
from rest_framework import serializers

from .models import Folder


class FolderSerializer(serializers.ModelSerializer):
    """
    Папка личного стола: имя и порядок, и больше ничего.

    Содержимое сюда **не вкладывается**, хотя экран показывает и то и другое.
    Вещи приезжают своей дверью — `/api/attachments/?bookmark_owner=…`, той
    же, что у материалов урока, — и второй вид того же списка означал бы
    второе место, где чинить показ файла, ссылки и записки. Экран берёт два
    запроса и складывает их сам; поиск по всему столу от этого не стоит ни
    одного запроса на букву.

    Числа «сколько внутри» тут поэтому тоже нет: экран считает его по тем же
    вещам, которые показывает, а посчитанное сервером расходилось бы с
    показанным ровно в тот момент, когда человек что-то кладёт.
    """

    # Пустоту ловит `validate_title`, а не DRF: его собственный отказ на
    # пустое поле приезжает без кода, то есть английской фразой в русском
    # интерфейсе. Обрезка тоже своя — иначе поле обрезало бы строку до
    # пустой и отказывало раньше, чем до проверки дойдёт очередь.
    title = serializers.CharField(
        max_length=120, allow_blank=True, trim_whitespace=False
    )

    class Meta:
        model = Folder
        fields = ("id", "title", "position")
        read_only_fields = ("id", "position")

    def validate_title(self, value):
        title = value.strip()
        if not title:
            api_error(
                Codes.FOLDER_TITLE_REQUIRED,
                "A folder is its name — it cannot be empty.",
                field="title",
            )
        return title
