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
    Any node of one's own — not only sections.

    Only a section may be a parent, but `structure_problems` is what says so:
    that way the user reads a sentence instead of PrimaryKeyRelatedField's
    flat «object does not exist».
    """
    user = requester(serializer)
    if user is None or not user.is_authenticated:
        return PlanNode.objects.none()
    return PlanNode.objects.filter(teacher=user)


def node_payload(node, number=None) -> dict:
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
    }


def tree_payload(owner) -> dict:
    tree = services.get_tree(owner)
    numbers = services.lesson_numbers(tree)

    nodes = []
    for branch in tree:
        payload = node_payload(branch.node, numbers.get(branch.node.pk))
        if branch.node.is_section:
            payload["children"] = [
                node_payload(child, numbers.get(child.pk)) for child in branch.children
            ]
        nodes.append(payload)

    return {"nodes": nodes, "counts": services.counts(tree)}


def flat_payload(owner) -> dict:
    lessons = services.flatten_lessons(owner)

    return {
        "lessons": [
            {
                **node_payload(item.node, item.number),
                "section_id": item.section.pk if item.section else None,
                "section_title": item.section.title if item.section else "",
            }
            for item in lessons
        ],
        "counts": services.counts(services.get_tree(owner)),
    }


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
            *CONTENT_FIELDS,
        )
        extra_kwargs = CONTENT_EXTRA_KWARGS

    def get_fields(self):
        fields = super().get_fields()
        fields["course"].queryset = teacher_courses(self)
        fields["parent"].queryset = own_nodes(self)
        fields["after"].queryset = own_nodes(self)
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

        after = attrs.get("after")
        if after is not None:
            if after.course_id != attrs["course"].pk:
                api_error(
                    Codes.ANCHOR_OTHER_CLASS,
                    "That node belongs to another course.",
                    field="after",
                )
            if after.parent_id != (attrs.get("parent").pk if attrs.get("parent") else None):
                api_error(
                    Codes.ANCHOR_OTHER_LEVEL,
                    "The node to insert after sits on another level.",
                    field="after",
                )

        return attrs

    def create(self, validated_data):
        after = validated_data.pop("after", None)
        parent = validated_data.get("parent")

        # the position is settled by place(); any value does until then
        node = PlanNode.objects.create(
            position=0, teacher=self.context["request"].user, **validated_data
        )

        index = (
            after.position + 1 if after is not None else len(services.level(node, parent))
        )
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
