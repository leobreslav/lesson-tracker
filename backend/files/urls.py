from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttachmentViewSet, LessonImageView

router = DefaultRouter()
router.register("attachments", AttachmentViewSet, basename="attachment")

urlpatterns = router.urls + [
    # картинка содержания адресуется файлом, а не вложением — см. вьюху
    path("images/<int:file_id>/", LessonImageView.as_view(), name="lesson-image"),
]
