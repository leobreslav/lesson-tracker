from django.urls import include, path
from rest_framework.routers import DefaultRouter
# назначения, методисты и состав — модели расписания, но принадлежат школе,
# поэтому отвечают под /api/school/ рядом с курсами и людьми
from schedule.views import (
    CourseAssignmentViewSet,
    CourseMethodistViewSet,
    CourseStudentViewSet,
    GradeLevelViewSet,
    SubjectViewSet,
)

from .views import (
    InvitationViewSet,
    MemberViewSet,
    MySchoolView,
    SchoolOverviewView,
)

router = DefaultRouter()
router.register("subjects", SubjectViewSet, basename="subject")
router.register("grades", GradeLevelViewSet, basename="gradelevel")
router.register("assignments", CourseAssignmentViewSet, basename="courseassignment")
router.register("methodists", CourseMethodistViewSet, basename="coursemethodist")
router.register("students", CourseStudentViewSet, basename="coursestudent")
router.register("members", MemberViewSet, basename="member")
router.register("invitations", InvitationViewSet, basename="invitation")

urlpatterns = [
    path("", MySchoolView.as_view(), name="my-school"),
    path("overview/", SchoolOverviewView.as_view(), name="school-overview"),
    path("", include(router.urls)),
]
