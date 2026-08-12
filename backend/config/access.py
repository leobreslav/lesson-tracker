"""
Who may see and change what.

There are exactly three access shapes in the project, and they live here
rather than in twenty querysets:

1. a school object, reading — the user belongs to the same school;
2. a school object, writing — plus the administrator role;
3. a personal object — it belongs to this teacher, inside a course of their
   own school.

Every viewset picks a base class below and says which ORM path leads from its
model to the school (``school_path``) or to the teacher (``teacher_path``).
Nothing else filters by hand: a forgotten filter is exactly the hole this
module exists to close.

Two different refusals, on purpose:

* a foreign school gives **404** — the object is not in the queryset at all,
  and a stranger should not learn that it exists;
* one's own school without the role gives **403** — the object is right
  there, the person simply may not change it.
"""

from config.errors import Codes, api_denied
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated


def user_school_id(user):
    """The school of a signed-in user, or None for everybody else."""
    if user is None or not user.is_authenticated:
        return None
    return user.school_id


class IsSchoolMember(BasePermission):
    """
    Signed in and attached to a school.

    A user with no school is a real, valid state — invited by nobody yet — so
    the answer names it with a code instead of a bare 403: the interface shows
    "ask your administrator" rather than a dead end.
    """

    def has_permission(self, request, view):
        if user_school_id(request.user) is None:
            api_denied(
                Codes.NO_SCHOOL,
                "You do not belong to any school yet.",
            )
        return True


class IsSchoolAdminForWrite(BasePermission):
    """Reading is for every member of the school, writing for its admins."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not request.user.is_school_admin:
            api_denied(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator can change this.",
            )
        return True


class IsSchoolAdmin(BasePermission):
    """The administrator role, whatever the method — reading included."""

    def has_permission(self, request, view):
        if not request.user.is_school_admin:
            api_denied(
                Codes.SCHOOL_ADMIN_REQUIRED,
                "Only a school administrator can see this.",
            )
        return True


class SchoolScopedViewSet(viewsets.ModelViewSet):
    """
    A school object: everybody in the school reads it, admins change it.

    `school_path` is the ORM path from this model to the school — "school"
    for the ones holding the key themselves, "year__school" for the calendar
    markup hanging off a year.
    """

    school_path = "school"
    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdminForWrite]

    def get_queryset(self):
        # the filter closes reading and writing at once: an object from
        # another school is simply not found, on any action including detail
        return super().get_queryset().filter(
            **{self.school_path: self.request.user.school_id}
        )


class TeacherScopedViewSet(viewsets.ModelViewSet):
    """
    A personal object: only its own teacher, and only inside their school.

    The role means nothing here — an administrator is a teacher with extra
    rights over the school's shared objects, not over other people's lessons.
    """

    teacher_path = "teacher"
    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get_queryset(self):
        return super().get_queryset().filter(**{self.teacher_path: self.request.user})
