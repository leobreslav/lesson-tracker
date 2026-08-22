"""
The superuser's door: every school, not just one's own.

Kept apart from `urls.py` on purpose — `/api/school/` is "my school" and
answers to the school's own administrator, `/api/schools/` is the list of
them all and answers only to a superuser. One prefix, one audience.
"""

from rest_framework.routers import DefaultRouter

from .views import SchoolViewSet

router = DefaultRouter()
router.register("", SchoolViewSet, basename="school")

urlpatterns = router.urls
