from config.errors import Codes, api_error
from django.db.models import Count
from rest_framework import serializers

from .models import (
    Attachment,
    KIND_FILE,
    KIND_LINK,
    KIND_TEXT,
    KINDS,
    OWNER_FIELDS,
    StoredFile,
)
from .services import INLINE_EXTENSIONS, shows_in_text


def with_sharing(queryset):
    """
    Attachments plus how many references their file has.

    Counted in the query rather than per row: «this file is used elsewhere»
    is drawn next to every attachment, and a lesson with six of them would
    otherwise ask the database six extra times to say so.

    Сортировка тут **не украшение, а починка**. `annotate` с агрегатом
    добавляет к запросу GROUP BY, и Django в таком запросе снимает
    `Meta.ordering` — молча: список приезжает в том порядке, в каком его
    вернула база. Полтора года это сходило с рук, потому что позиция росла
    вместе с id и порядки совпадали; первое же перекладывание закладки в
    другую папку (позиция меняется, id остаётся) совпадение сломало — вещь
    садилась не туда, куда её положили.

    Порядок повторяет `Attachment.Meta.ordering` намеренно: он и есть ответ
    на вопрос «в каком порядке человек это разложил».
    """
    return (
        queryset.select_related("stored_file")
        .annotate(reference_count=Count("stored_file__attachments"))
        .order_by("position", "id")
    )


class AttachmentSerializer(serializers.ModelSerializer):
    """One reference, as the panel shows it."""

    # Папка на личном столе: единственное «место», которое у ссылки можно
    # переменить после заведения.
    #
    # Владельца переменить нельзя — это был бы способ утащить чужой урок к
    # себе, — а вот переложить своё из папки в папку человек должен уметь,
    # не загружая файл заново. Отсюда и выборка: только свои папки, и только
    # у того, что и так лежит на своём столе (см. `validate_bookmark_folder`).
    bookmark_folder = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    file_name = serializers.CharField(source="stored_file.original_name", default=None)
    size = serializers.IntegerField(source="stored_file.size", default=None)
    content_type = serializers.CharField(
        source="stored_file.content_type", default=None
    )
    is_shared = serializers.SerializerMethodField()
    # объект в бакете, а не ссылка на него: разметка содержания называет
    # именно его, потому что переживает копирование плана и откат
    file = serializers.IntegerField(source="stored_file_id", read_only=True)

    class Meta:
        model = Attachment
        fields = (
            "id",
            "kind",
            "title",
            # приписка своими словами: «зачем это мне». У записки на личном
            # столе она и есть весь текст, у материала урока — пометка
            "note",
            "url",
            "position",
            "inline",
            "file",
            "file_name",
            "size",
            "content_type",
            "is_shared",
            "bookmark_folder",
            # «видно только учителю» — не показ, а право, и правится оно тут
            # же, строкой в списке: решают это в тот же заход, что и
            # прикладывают, а перепутанное решение исправляют немедленно
            "staff_only",
        )
        read_only_fields = ("id", "kind", "url", "position", "inline")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        # сериализатор ходит и без запроса — вложенным в чужой ответ,
        # например, — и тогда выбирать папку некому: пустая выборка
        # означает «этим полем ничего не изменить»
        if request is not None:
            from .access import writable_shelf_folders

            fields["bookmark_folder"].queryset = writable_shelf_folders(request.user)
        return fields

    def validate_bookmark_folder(self, value):
        """
        Разложить по папкам можно то, что и так лежит на своём столе.

        Иначе это не «переложить», а «сменить владельца»: PATCH с папкой у
        вложения урока увёл бы материал курса на личную полку — молча и
        необратимо для тех, кто ведёт курс после.
        """
        if self.instance is not None and self.instance.bookmark_owner_id is None:
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "Only what lies on a personal shelf can be put in a folder.",
                field="bookmark_folder",
            )
        return value

    def update(self, instance, validated_data):
        """
        Переложенное встаёт в конец, а не остаётся на прежнем месте.

        Позиция считается по столу целиком, поэтому вещь, переехавшая из
        первой папки в третью, села бы в её середину — на место, которого
        человек ей не назначал. Порядок внутри папки от пересчёта не
        страдает: он относительный.
        """
        moved = (
            "bookmark_folder" in validated_data
            and validated_data["bookmark_folder"] != instance.bookmark_folder
        )
        if moved and instance.bookmark_owner_id is not None:
            from .services import next_position

            validated_data["position"] = next_position(
                bookmark_owner_id=instance.bookmark_owner_id
            )
        return super().update(instance, validated_data)

    def validate_staff_only(self, value):
        """
        Прятать можно только то, что классу вообще показывают.

        План и полку ученик не читает вовсе, тетрадь — своя собственная, и
        «спрятать» там значило бы спрятать её от хозяина. Признак имеет смысл
        ровно у вложения работы, и молча принятый в остальных местах он
        обещал бы право, которого не даёт.
        """
        owner = self.instance
        if value and owner is not None and owner.work_id is None:
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "Only what is attached to a work can be hidden from the class.",
                field="staff_only",
            )
        return value

    def get_is_shared(self, obj) -> bool:
        # the annotation when it is there, the model's own answer otherwise
        count = getattr(obj, "reference_count", None)
        if count is None:
            return obj.is_shared
        return count > 1


class AttachmentCreateSerializer(serializers.Serializer):
    """
    Adding a reference: either an uploaded file or an address on the web.

    The row it hangs off is validated against what this person may write, so
    a plan node id belonging to a colleague is simply not a valid choice.
    """

    plan_row = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    template_row = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    student_work = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    work = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    # Личный стол: владелец — человек, и назвать можно только себя (выборка
    # в `get_fields`). Спрашивается он телом, а не берётся из токена молча,
    # ровно потому же, почему остальные владельцы: «куда это положить» —
    # вопрос запроса, и пятый ответ на него должен выглядеть как остальные
    # четыре, иначе `OWNER_FIELDS` перестаёт быть одним списком.
    bookmark_owner = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    # Общая полка школы: кладёт администратор, видят все сотрудники.
    school_shelf = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    # Не владелец, а адрес внутри стола: пусто — «положить на виду».
    bookmark_folder = serializers.PrimaryKeyRelatedField(
        queryset=Attachment.objects.none(), required=False, allow_null=True
    )
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    file = serializers.FileField(required=False)
    # вид называется только у записи: у файла и ссылки он и так виден по
    # тому, что прислали, а у записи присылать нечего
    kind = serializers.ChoiceField(choices=KINDS, required=False)
    # «эта картинка встала в текст» — про распоряжение ею, а не про вид
    inline = serializers.BooleanField(required=False, default=False)
    # Кому видно: классу или только учителю. Спрашивается **при загрузке**, а
    # не переключается после, и это про окно, а не про удобство: ответы к
    # контрольной, приложенные видимыми и спрятанные через секунду, эту
    # секунду были открыты всему классу — а класс в этот момент как раз и
    # смотрит на работу.
    staff_only = serializers.BooleanField(required=False, default=False)

    def get_fields(self):
        from .access import (
            writable_plan_rows,
            writable_school_shelves,
            writable_shelf_folders,
            writable_shelf_owners,
            writable_student_works,
            writable_template_rows,
            writable_works,
        )

        fields = super().get_fields()
        user = self.context["request"].user
        fields["plan_row"].queryset = writable_plan_rows(user)
        fields["template_row"].queryset = writable_template_rows(user)
        fields["student_work"].queryset = writable_student_works(user)
        fields["work"].queryset = writable_works(user)
        fields["bookmark_owner"].queryset = writable_shelf_owners(user)
        fields["bookmark_folder"].queryset = writable_shelf_folders(user)
        fields["school_shelf"].queryset = writable_school_shelves(user)
        return fields

    def validate(self, attrs):
        # папка названа, а хозяин нет — обычный случай экрана закладок:
        # раскладывают по своим папкам, и хозяин у них по построению один.
        # Выводится он из папки, а не берётся из токена: так владелец
        # по-прежнему приезжает телом запроса, и правило «ровно один
        # владелец» проверяет то же, что и у остальных четверых
        folder = attrs.get("bookmark_folder")
        if folder is not None and attrs.get("bookmark_owner") is None:
            attrs["bookmark_owner"] = folder.owner

        owners = {name: attrs.get(name) for name in OWNER_FIELDS}
        named = [name for name, value in owners.items() if value is not None]

        if len(named) != 1:
            api_error(
                Codes.ATTACHMENT_OWNER_REQUIRED,
                "Name exactly one owner: «plan_row», «template_row», «work», "
                "«student_work», «bookmark_owner» or «school_shelf».",
                field="plan_row",
            )

        if attrs.get("staff_only") and owners["work"] is None:
            # прятать можно только то, что классу вообще показывают: план и
            # полку он не читает, а тетрадь — его собственная
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "Only what is attached to a work can be hidden from the class.",
                field="staff_only",
            )

        plan_row, template_row = owners["plan_row"], owners["template_row"]
        row = owners[named[0]]
        if getattr(row, "is_section", False) or getattr(row, "is_header", False):
            api_error(
                Codes.CONTENT_ON_SECTION,
                "A section header holds no lesson content.",
                field="plan_row" if plan_row else "template_row",
            )

        upload = attrs.get("file")
        url = attrs.get("url")

        if attrs.get("inline"):
            # в текст встаёт картинка, и только она: показать ссылку или
            # запись нечем, а из файлов показывается не всякий
            if upload is None or not shows_in_text(upload.name):
                api_error(
                    Codes.ATTACHMENT_NOT_AN_IMAGE,
                    "Only an image can stand inside the lesson text.",
                    field="file",
                    allowed=sorted(INLINE_EXTENSIONS),
                )
            if (
                owners["bookmark_owner"] is not None
                or owners["school_shelf"] is not None
            ):
                # на полке нет текста, в который встают картинки: закладка
                # это сама вещь, а не абзац с картинкой внутри. Верно для
                # обеих полок, личной и школьной
                api_error(
                    Codes.ATTACHMENT_KIND_MISMATCH,
                    "A shelf has no text to stand in.",
                    field=(
                        "bookmark_owner"
                        if owners["bookmark_owner"] is not None
                        else "school_shelf"
                    ),
                )
            if owners["student_work"] is not None:
                # у работы ученика текста нет — есть его тетрадь. Ставить
                # картинку «в текст» тут некуда, и `inline` означал бы
                # фотографию, которую не видно ни в списке, ни в содержании.
                # У самой работы (`work`) текст есть — пояснения к заданию, —
                # и картинка в них законна
                api_error(
                    Codes.ATTACHMENT_KIND_MISMATCH,
                    "A student's work has no text to stand in.",
                    field="student_work",
                )

        if attrs.get("kind") == KIND_TEXT:
            if upload or url:
                api_error(
                    Codes.ATTACHMENT_KIND_MISMATCH,
                    "A text resource carries neither a file nor an address.",
                    field="file",
                )
            if not (attrs.get("title") or "").strip():
                api_error(
                    Codes.ATTACHMENT_TITLE_REQUIRED,
                    "A text resource is its title — it cannot be empty.",
                    field="title",
                )
            return attrs

        if bool(upload) == bool(url):
            api_error(
                Codes.ATTACHMENT_KIND_MISMATCH,
                "Send either a file or an address, not both and not neither.",
                field="file",
            )

        attrs["kind"] = KIND_FILE if upload else KIND_LINK
        return attrs


class StoredFileSerializer(serializers.ModelSerializer):
    """Only the admin and the cleanup report need this."""

    class Meta:
        model = StoredFile
        fields = ("id", "key", "original_name", "size", "content_type", "created_at")
