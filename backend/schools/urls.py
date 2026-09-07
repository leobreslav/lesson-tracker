from django.urls import include, path
from rest_framework.routers import DefaultRouter
# назначения, методисты и состав — модели расписания, но принадлежат школе,
# поэтому отвечают под /api/school/ рядом с курсами и людьми
from families.views import GuardianshipViewSet
from schedule.views import (
    BellsView,
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
# родство — модель семьи, но заводит и снимает его школа, поэтому здесь
router.register("guardianships", GuardianshipViewSet, basename="guardianship")
router.register("members", MemberViewSet, basename="member")
router.register("invitations", InvitationViewSet, basename="invitation")

urlpatterns = [
    path("", MySchoolView.as_view(), name="my-school"),
    # звонки — справочник школы рядом с предметами и параллелями, но правятся
    # целиком, поэтому своя вьюха, а не вьюсет: номер урока и есть ключ
    path("bells/", BellsView.as_view(), name="school-bells"),
    path("overview/", SchoolOverviewView.as_view(), name="school-overview"),
    path("", include(router.urls)),
]
