from config.access import IsSchoolAdmin, IsSchoolAdminForWrite, IsSchoolMember
from django.contrib.auth import get_user_model
from rest_framework import mixins, viewsets
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from .models import Invitation
from .serializers import InvitationSerializer, MemberSerializer, SchoolSerializer

User = get_user_model()


class MySchoolView(RetrieveAPIView):
    """The school of the requester. Read-only: renaming is an admin job."""

    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get_object(self):
        return self.request.user.school


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
