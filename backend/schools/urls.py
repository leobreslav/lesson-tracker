from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import InvitationViewSet, MemberViewSet, MySchoolView

router = DefaultRouter()
router.register("members", MemberViewSet, basename="member")
router.register("invitations", InvitationViewSet, basename="invitation")

urlpatterns = [
    path("", MySchoolView.as_view(), name="my-school"),
    path("", include(router.urls)),
]
