from config.access import IsSchoolMember, IsTeacher
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Folder
from .serializers import FolderSerializer


class BookmarkFolderViewSet(viewsets.ModelViewSet):
    """
    Папки личного стола: свои, и только свои.

    Не `SchoolScopedViewSet` и не `CourseScopedViewSet`, и это первый такой
    вьюсет за долгое время. Обе базовые формы отвечают на вопрос «чей это
    объект» через школу или курс, а у стола владелец — человек: администратор
    школы здесь не имеет прав больше учителя, а снятие с курса ничего не
    забирает. Выборка поэтому своя, из одного условия, и закрывает она разом
    чтение, правку и снос — чужая папка просто не находится (404), как объект
    другой школы.

    `IsTeacher` стоит потому, что стол — раздел сотрудника: у ученика и
    родителя свой интерфейс, и закладок в нём нет. `IsSchoolMember` рядом —
    потому что вещи на столе бывают файлами, а файл принадлежит школе
    (`StoredFile.school`), и человеку без школы его негде хранить.
    """

    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher]

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        """
        Хозяин берётся из токена, а не из тела: чужой стол не пополняют.

        Порядок — в конец списка. Заводят папку тогда, когда появилось что
        разложить, и вставать она должна там, где на неё смотрят, а не среди
        уже разобранного.
        """
        owner = self.request.user
        serializer.save(
            owner=owner,
            position=Folder.objects.filter(owner=owner).count(),
        )
