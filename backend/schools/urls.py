from django.urls import include, path
from rest_framework.routers import DefaultRouter
# the timetable is a schedule model, but it is the school's, so it answers
# under /api/school/ next to the courses and the people
from schedule.views import MasterSlotViewSet

from .views import (
    InvitationViewSet,
    MemberViewSet,
    MySchoolView,
    SchoolViewSet,
)

router = DefaultRouter()
router.register("master-slots", MasterSlotViewSet, basename="masterslot")
router.register("members", MemberViewSet, basename="member")
router.register("invitations", InvitationViewSet, basename="invitation")

urlpatterns = [
    path("", MySchoolView.as_view(), name="my-school"),
    path("", include(router.urls)),
]
