from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from schedule.models import SchoolClass

from . import services
from .models import PlanNode


def own_classes(serializer):
    user = getattr(serializer.context.get("request"), "user", None)
    if user is None or not user.is_authenticated:
        return SchoolClass.objects.none()
    return SchoolClass.objects.filter(owner=user)


def own_nodes(serializer):
    """
    Любые свои узлы — не только папки.

    Родителем может быть только папка, но проверяет это
    `structure_problems`: так пользователь получает понятный текст вместо
    сухого «объект не найден» от PrimaryKeyRelatedField.
    """
    return PlanNode.objects.filter(school_class__in=own_classes(serializer))


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
    }


def tree_payload(school_class) -> dict:
    tree = services.get_tree(school_class)
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


def flat_payload(school_class) -> dict:
    lessons = services.flatten_lessons(school_class)

    return {
        "lessons": [
            {
                **node_payload(item.node, item.number),
                "section_id": item.section.pk if item.section else None,
                "section_title": item.section.title if item.section else "",
            }
            for item in lessons
        ],
        "counts": services.counts(services.get_tree(school_class)),
    }


def layout_payload(entries) -> dict:
    """Раскладка в JSON. Нигде не хранится — считается на каждый запрос."""

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
        fields = ("id", "school_class", "parent", "is_section", "title", "note", "after")

    def get_fields(self):
        fields = super().get_fields()
        fields["school_class"].queryset = own_classes(self)
        fields["parent"].queryset = own_nodes(self)
        fields["after"].queryset = own_nodes(self)
        return fields

    def validate(self, attrs):
        problems = services.structure_problems(
            school_class_id=attrs["school_class"].pk,
            parent=attrs.get("parent"),
            is_section=attrs.get("is_section", False),
        )
        if problems:
            raise serializers.ValidationError(problems)

        after = attrs.get("after")
        if after is not None:
            if after.school_class_id != attrs["school_class"].pk:
                raise serializers.ValidationError({"after": "Узел из другого класса."})
            if after.parent_id != (attrs.get("parent").pk if attrs.get("parent") else None):
                raise serializers.ValidationError(
                    {"after": "Узел «после» лежит на другом уровне."}
                )

        return attrs

    def create(self, validated_data):
        after = validated_data.pop("after", None)
        parent = validated_data.get("parent")
        school_class = validated_data["school_class"]

        # позиция уточнится в place(), а пока хватит любой
        node = PlanNode.objects.create(position=0, **validated_data)

        index = (
            after.position + 1
            if after is not None
            else len(services.level(school_class, parent))
        )
        services.place(node, parent, index)

        return node


class PlanNodeUpdateSerializer(serializers.ModelSerializer):
    """Правка содержимого узла. Структура меняется через move/move_to."""

    class Meta:
        model = PlanNode
        fields = ("id", "parent", "position", "is_section", "title", "note")
        read_only_fields = ("parent", "position", "is_section")


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


def check_structure(node, parent):
    """Проверка правил дерева при переносе — та же, что в модели."""
    problems = services.structure_problems(
        school_class_id=node.school_class_id,
        parent=parent,
        is_section=node.is_section,
    )
    if problems:
        # список на каждое поле: так же выглядят ошибки сериализатора,
        # клиенту не приходится разбирать два формата
        raise serializers.ValidationError(
            {field: [message] for field, message in problems.items()}
        )


def to_drf_error(error: DjangoValidationError) -> serializers.ValidationError:
    return serializers.ValidationError(
        error.message_dict if hasattr(error, "message_dict") else error.messages
    )
