from rest_framework.routers import DefaultRouter

from .views import DayExceptionViewSet, SchoolYearViewSet, TermViewSet

router = DefaultRouter()
router.register("years", SchoolYearViewSet, basename="schoolyear")
router.register("exceptions", DayExceptionViewSet, basename="dayexception")
router.register("terms", TermViewSet, basename="term")

urlpatterns = router.urls
