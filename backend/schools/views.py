from config.access import (
    IsSchoolAdmin,
    IsSchoolAdminForWrite,
    IsSchoolMember,
    IsSuperuser,
)
from collections import Counter

from config.errors import Codes, api_error
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Invitation, School
from .serializers import (
    InvitationSerializer,
    MemberSerializer,
    SchoolInviteSerializer,
    SchoolSerializer,
)

User = get_user_model()


def describe(blocked: ProtectedError) -> str:
    """«2 members, 3 files» — what a ProtectedError is actually about."""
    counts = Counter(
        obj._meta.verbose_name_plural for obj in blocked.protected_objects
    )
    return ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))


class MySchoolView(RetrieveUpdateAPIView):
    """
    The school of the requester: everybody reads it, its admins rename it.

    A school object like any other, so it goes through the same permission
    as the calendar and the courses.
    """

    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdminForWrite]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user.school


class SchoolViewSet(viewsets.ModelViewSet):
    """
    Every school, for a superuser.

    This is the one section where `is_superuser` means something inside the
    app. Creating a school cannot come from within a school, and the first
    administrator cannot invite themselves, so somebody outside the schools
    has to do both — otherwise every new school would need a trip to
    /admin/.

    A superuser is still an ordinary member of their own school everywhere
    else: this viewset hands out schools, not power over the work inside
    them.
    """

    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated, IsSuperuser]
    queryset = School.objects.prefetch_related("members").order_by("name")

    def perform_destroy(self, instance):
        """
        A school with anything in it stays. Several PROTECTs say so.

        People are the usual blocker — deleting the school would strand their
        calendar, courses and lessons — but not the only one: subjects and
        stored files hold it too, and a school can outlive its last member.
        So the answer names what is actually in the way rather than assuming
        it is people; a message that says «2 members» about three files sends
        somebody looking in the wrong place.
        """
        try:
            instance.delete()
        except ProtectedError as blocked:
            api_error(
                Codes.SCHOOL_IN_USE,
                f"«{instance.name}» is still in use: {describe(blocked)}. "
                "Clear it first.",
                name=instance.name,
                members=instance.members.count(),
                blocked_by=describe(blocked),
            )

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """
        Invite the first administrator of a school.

        The same invitation a school admin would write, only from outside:
        the person signs in through Google on that address and arrives with
        the role already granted.
        """
        school = self.get_object()
        form = SchoolInviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        email = form.validated_data["email"]

        invitation, created = Invitation.objects.get_or_create(
            school=school,
            email=email,
            defaults={"is_school_admin": True, "created_by": request.user},
        )
        if not created and not invitation.is_school_admin:
            # the address was already invited as a plain teacher — promote it
            invitation.is_school_admin = True
            invitation.save(update_fields=["is_school_admin"])

        return Response(
            InvitationSerializer(invitation).data, status=201 if created else 200
        )


class MemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    The people of the school.

    Everybody sees the list — knowing who else teaches here is not a secret
    and the schedule shows their names anyway. Only an administrator hands
    the role over, and there is no deletion: a person leaving the school is
    an operation with consequences for their lessons, and this stage does not
    define what should happen to them.
    """

    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdminForWrite]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return User.objects.filter(school_id=self.request.user.school_id).order_by(
            "first_name", "last_name", "email"
        )


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Invitations of this school.

    Administrators only, in both directions: the list of addresses somebody
    wrote down is nobody else's business.

    An accepted invitation is kept — it is the record of who let whom in.
    Deleting one only withdraws an invitation nobody has used yet; it does not
    remove a member who already joined.
    """

    serializer_class = InvitationSerializer
    # admins in both directions, so IsSchoolAdmin rather than …ForWrite
    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdmin]

    def get_queryset(self):
        return Invitation.objects.filter(school_id=self.request.user.school_id)

    def perform_create(self, serializer):
        serializer.save(
            school=self.request.user.school, created_by=self.request.user
        )
