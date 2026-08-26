"""
Справочник видов работ: читают все свои, правит администратор.

Та же форма доступа, что у систем оценивания, предметов и параллелей, и берётся
она тем же классом — `IsSchoolAdminForWrite`. Учителю список нужен на каждой
работе, поэтому читать может каждый.
"""

from config.access import IsSchoolAdminForWrite, IsSchoolMember, IsTeacher
from config.errors import Codes, api_error
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import kinds
from .models import WorkKind


class WorkKindsView(APIView):
    """Список видов школы, заведение и типовой набор."""

    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get(self, request):
        school = request.user.school
        return Response(
            {
                "kinds": [kinds.payload(kind) for kind in school.work_kinds.all()],
                "may_edit": request.user.is_school_admin,
            }
        )

    def post(self, request):
        school = request.user.school

        if request.data.get("typical"):
            return Response({"added": kinds.add_typical(school, request.user.language)})

        name = (request.data.get("name") or "").strip()
        label = (request.data.get("label") or "").strip()

        if not name:
            api_error(
                Codes.WORK_KIND_NAME_REQUIRED, "A kind needs a name.", field="name"
            )
        if not label:
            # Метка — то, чем вид виден в журнале, и без неё столбец нечем
            # подписать. Выводить её из имени первой буквой нельзя: «Проект»
            # и «Проверочная» дали бы одну и ту же.
            api_error(
                Codes.WORK_KIND_LABEL_REQUIRED,
                "A kind needs a short label for the gradebook.",
                field="label",
            )
        if school.work_kinds.filter(name=name).exists():
            api_error(
                Codes.WORK_KIND_NAME_TAKEN,
                "The school already has a kind with that name.",
                field="name",
            )

        kind = WorkKind.objects.create(
            school=school,
            name=name,
            label=label[:4],
            color=request.data.get("color") or "slate",
            counts_to_term=bool(request.data.get("counts_to_term")),
            position=school.work_kinds.count(),
        )
        return Response(kinds.payload(kind), status=201)


class WorkKindView(APIView):
    """Один вид: имя, метка, цвет, умолчание итога и разрешение."""

    permission_classes = [
        IsAuthenticated,
        IsSchoolMember,
        IsTeacher,
        IsSchoolAdminForWrite,
    ]

    def get_object(self, request, pk):
        kind = WorkKind.objects.filter(pk=pk, school=request.user.school).first()
        if kind is None:
            api_error(Codes.OTHER_SCHOOL, "No such kind of work.", field="id")
        return kind

    def patch(self, request, pk):
        kind = self.get_object(request, pk)

        if "name" in request.data:
            kind.name = (request.data["name"] or "").strip() or kind.name
        if "label" in request.data:
            kind.label = ((request.data["label"] or "").strip() or kind.label)[:4]
        if "color" in request.data:
            kind.color = request.data["color"] or kind.color
        if "counts_to_term" in request.data:
            kind.counts_to_term = bool(request.data["counts_to_term"])
        if "is_allowed" in request.data:
            kind.is_allowed = bool(request.data["is_allowed"])
        if "position" in request.data:
            kind.position = int(request.data["position"])
        kind.save()

        return Response(kinds.payload(kind))

    def delete(self, request, pk):
        kind = self.get_object(request, pk)
        # работы этого вида остаются и вида просто лишаются (`SET_NULL`): они
        # про то, что уже решали, а не про то, как школа их называет
        kind.delete()
        return Response(status=204)
