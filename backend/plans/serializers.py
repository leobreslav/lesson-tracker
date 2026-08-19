from config.errors import Codes, api_error
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from schedule.serializers import teacher_courses

from . import services
from .content import CONTENT_EXTRA_KWARGS, CONTENT_FIELDS, content_problems
from .models import PlanNode


def raise_content_error(*, is_section: bool, values):
    """Content on a section header, said the same way the model says it."""
    for field, message in content_problems(is_section=is_section, values=values).items():
        api_error(Codes.CONTENT_ON_SECTION, message, field=field)


def requester(serializer):
    return getattr(serializer.context.get("request"), "user", None)


def own_nodes(serializer):
    """
    Любой узел из планов своих курсов — не только папка.

    Родителем может быть только папка, но говорит об этом
    `structure_problems`: так человек читает фразу, а не сухое «object does
    not exist» от PrimaryKeyRelatedField.
    """
    from schedule.models import Course

    user = requester(serializer)
    if user is None or not user.is_authenticated:
        return PlanNode.objects.none()
    # право, а не принадлежность: администратор школы правит её курсы
    return PlanNode.objects.filter(course__in=Course.objects.writable_by(user))


def node_payload(node, number=None, *, taught=()) -> dict:
    return {
        "id": node.pk,
        "parent": node.parent_id,
        "position": node.position,
        "is_section": node.is_section,
        "title": node.title,
        "note": node.note,
        # сквозной номер считается на лету, у папок его нет
        "number": number,
        # в дереве едут только пометки: само содержание может быть длинным,
        # а таблица плана показывает лишь значок. Текст берётся детально,
        # запросом на конкретный урок
        "has_content": node.has_content,
        "attachments": getattr(node, "attachment_count", 0),
        # урок проведён: за ним записан час, и позиция ему больше не указ.
        # Такую строку нельзя переставлять — раскладка показала бы её по
        # записи, а соседей по позиции, и они бы столкнулись. Признак едет в
        # дереве, а не выводится из ленты слотов: лента приезжает не всегда
        # (даты можно выключить), а ручку перетаскивания прятать надо всегда
        "taught": node.pk in taught,
    }


def tree_payload(course_id: int) -> dict:
    from schedule.models import Slot

    tree = services.get_tree(course_id)
    numbers = services.lesson_numbers(tree)
    # один запрос на всё дерево: строк плана бывает две сотни
    taught = set(
        Slot.objects.filter(course_id=course_id, lesson__isnull=False).values_list(
            "lesson_id", flat=True
        )
    )

    nodes = []
    for branch in tree:
        payload = node_payload(branch.node, numbers.get(branch.node.pk), taught=taught)
        if branch.node.is_section:
            payload["children"] = [
                node_payload(child, numbers.get(child.pk), taught=taught)
                for child in branch.children
            ]
        nodes.append(payload)

    return {"nodes": nodes, "counts": services.counts(tree)}


def layout_payload(entries) -> dict:
    """The layout as JSON. Stored nowhere — recomputed on every request."""

    def slot_payload(slot):
        return slot and {
            "id": slot.pk,
            "date": slot.date,
            "lesson_number": slot.lesson_number,
            "is_extra": slot.is_extra,
        }

    def lesson_payload(lesson):
        return lesson and {
            "id": lesson.node.pk,
            "title": lesson.node.title,
            "number": lesson.number,
            # тема — папка, в которой лежит урок; у уроков верхнего уровня её нет
            "section_id": lesson.section.pk if lesson.section else None,
            "section_title": lesson.section.title if lesson.section else None,
        }

    return {
        "entries": [
            {
                "status": entry.status,
                "slot": slot_payload(entry.slot),
                "plan_row": lesson_payload(entry.lesson),
                "term_id": entry.term.pk if entry.term else None,
                "term_name": entry.term.name if entry.term else None,
            }
            for entry in entries
        ]
    }


class PlanNodeCreateSerializer(serializers.ModelSerializer):
    # вставить сразу после этого узла; без него — в конец уровня
    after = serializers.PrimaryKeyRelatedField(
        queryset=PlanNode.objects.none(), required=False, allow_null=True, write_only=True
    )
    # ...или сразу перед ним. Симметричная пара нужна экрану «Сегодня»:
    # «мы всё ещё на синусе» значит, что строку надо дописать **перед** тем
    # уроком, который раскладка предлагала, — а его сосед сверху на том
    # экране неизвестен, там нет дерева плана
    before = serializers.PrimaryKeyRelatedField(
        queryset=PlanNode.objects.none(), required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = PlanNode
        fields = (
            "id",
            "course",
            "parent",
            "is_section",
            "title",
            "note",
            "after",
            "before",
            *CONTENT_FIELDS,
        )
        extra_kwargs = CONTENT_EXTRA_KWARGS

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        fields["parent"].queryset = own_nodes(self)
        fields["after"].queryset = own_nodes(self)
        fields["before"].queryset = own_nodes(self)
        return fields

    def validate(self, attrs):
        raise_content_error(
            is_section=attrs.get("is_section", False), values=attrs
        )

        problems = services.structure_problems(
            course_id=attrs["course"].pk,
            parent=attrs.get("parent"),
            is_section=attrs.get("is_section", False),
        )
        raise_structure_error(problems)

        for side in ("after", "before"):
            anchor = attrs.get(side)
            if anchor is None:
                continue
            if anchor.course_id != attrs["course"].pk:
                api_error(
                    Codes.ANCHOR_OTHER_CLASS,
                    "That node belongs to another course.",
                    field=side,
                )
            if anchor.parent_id != (
                attrs.get("parent").pk if attrs.get("parent") else None
            ):
                api_error(
                    Codes.ANCHOR_OTHER_LEVEL,
                    f"The node to insert {side} sits on another level.",
                    field=side,
                )

        return attrs

    def create(self, validated_data):
        after = validated_data.pop("after", None)
        before = validated_data.pop("before", None)
        parent = validated_data.get("parent")

        # the position is settled by place(); any value does until then
        node = PlanNode.objects.create(position=0, **validated_data)

        if after is not None:
            index = after.position + 1
        elif before is not None:
            index = before.position
        else:
            index = len(services.level(node.course_id, parent))
        services.place(node, parent, index)

        return node


class PlanNodeUpdateSerializer(serializers.ModelSerializer):
    """
    Editing a node. Structure moves through move/move_to.

    The four content fields are Markdown and are stored exactly as typed —
    see `plans.content` for why nothing here ever turns them into HTML.
    """

    class Meta:
        model = PlanNode
        fields = (
            "id",
            "parent",
            "position",
            "is_section",
            "title",
            "note",
            *CONTENT_FIELDS,
        )
        read_only_fields = ("parent", "position", "is_section")
        extra_kwargs = CONTENT_EXTRA_KWARGS

    def validate(self, attrs):
        raise_content_error(
            is_section=self.instance.is_section if self.instance else False,
            values=attrs,
        )
        return attrs


class PlanNodeDetailSerializer(PlanNodeUpdateSerializer):
    """One lesson with everything the side panel needs, attachments included."""

    attachments = serializers.SerializerMethodField()

    class Meta(PlanNodeUpdateSerializer.Meta):
        fields = PlanNodeUpdateSerializer.Meta.fields + ("attachments",)

    def get_attachments(self, obj):
        from files.serializers import AttachmentSerializer, with_sharing

        return AttachmentSerializer(
            with_sharing(obj.attachments.all()), many=True
        ).data


class MoveSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=services.DIRECTIONS)


class SplitSerializer(serializers.Serializer):
    """Название новой темы — больше разрезу ничего не нужно."""

    title = serializers.CharField(max_length=200)


class MoveToSerializer(serializers.Serializer):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=PlanNode.objects.none(), allow_null=True
    )
    position = serializers.IntegerField(min_value=0)

    def get_fields(self):
        fields = super().get_fields()
        fields["parent"].queryset = own_nodes(self)
        return fields


def raise_structure_error(problems):
    """Turn the first tree problem into a coded API error."""
    for field, (code, message) in problems.items():
        api_error(code, message, field=field)


def check_structure(node, parent):
    """The same tree rules as in the model, applied when moving a node."""
    raise_structure_error(
        services.structure_problems(
            course_id=node.course_id,
            parent=parent,
            is_section=node.is_section,
        )
    )


def to_drf_error(error: DjangoValidationError) -> serializers.ValidationError:
    return serializers.ValidationError(
        error.message_dict if hasattr(error, "message_dict") else error.messages
    )


# --- утверждение плана методистом ---


def person(user) -> dict | None:
    """Человек так, как его показывают в чужом списке: имя и адрес."""
    if user is None:
        return None

    name = f"{user.first_name} {user.last_name}".strip()
    return {"id": user.pk, "name": name or user.email, "email": user.email}


def request_payload(baseline) -> dict | None:
    """Поданный, возвращённый или отозванный запрос — как есть."""
    if baseline is None:
        return None

    return {
        "id": baseline.pk,
        "status": baseline.status,
        "created_at": baseline.created_at,
        "submitted_at": baseline.submitted_at,
        "approved_at": baseline.approved_at,
        "reviewer": person(baseline.reviewer),
        "comment": baseline.comment,
        "self_approved": baseline.self_approved,
        "lessons": sum(1 for row in baseline.rows.all() if not row.is_section),
    }


def baseline_payload(approved, pending, methodists, subject=None) -> dict:
    """
    Весь блок «эталон» одним ответом.

    Утверждённое и то, что в работе, — разные вещи и живут рядом: пока новый
    снимок ждёт методиста, расхождение считается от прежнего утверждённого,
    и на экране должны быть видны оба.
    """
    return {
        "approved": request_payload(approved),
        "request": request_payload(pending),
        "methodists": [person(row.user) for row in methodists],
        # предмет нужен, чтобы отказ «методист не назначен» назвал его, не
        # спрашивая сервер: список методистов у страницы уже есть
        "subject": subject,
    }
