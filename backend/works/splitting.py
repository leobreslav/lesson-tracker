"""
Разбор одного скана на работы учеников.

Класс написал контрольную на бумаге, учитель отсканировал всё пачкой — на
выходе одна длинная книга, где работы идут подряд, а порядок сдачи
произвольный. Разложить её по ученикам может только человек: титульный лист
опознаётся глазами, а «каждая работа два листа» — правило, которое ломается
на первом же, кто взял третий, и ломается **молча**: съезжает весь хвост.

Поэтому здесь нет ни угадывания, ни распознавания. На вход приходит
разметка, которую сделал человек: кому какие страницы. Автоматика (QR на
титульном листе) когда-нибудь будет предзаполнять эту же разметку, а не
заменять её — потому что и она будет ошибаться, а исправлять всё равно
руками.

Единственная библиотека, знающая про PDF на сервере, — `pypdf`, и живёт она
в этом файле. Картинки страниц рисует браузер: тащить растеризатор
(poppler, PyMuPDF) на сервер ради превью незачем, а файл у человека и так
уже в руках.

**Исходник не сохраняется.** Он лежит у учителя на диске, а в системе был бы
одним файлом, где собраны работы всего класса, — самым опасным, что тут
может быть. Перерезать — значит загрузить его ещё раз; это дешевле, чем
хранить и охранять.
"""

from dataclasses import dataclass
from io import BytesIO

from config.errors import Codes, api_error


@dataclass(frozen=True)
class Piece:
    """Кусок разметки: чья работа и с какой по какую страницу."""

    student_id: int
    first: int
    last: int

    @property
    def pages(self) -> range:
        """Страницы куска, 1-based и включительно — как их видит человек."""
        return range(self.first, self.last + 1)


class SplitError(Exception):
    """Файл не читается как PDF. Отказ, а не «разберём как получится»."""


def read_pages(data: bytes) -> int:
    """Сколько страниц в присланной книге. Заодно проверка, что это PDF."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        return len(PdfReader(BytesIO(data)).pages)
    except (PdfReadError, OSError, ValueError) as error:
        raise SplitError(str(error)) from error


def check_plan(pieces, *, pages: int, students) -> None:
    """
    Разметка целиком, до единой записи в базу.

    Проверяется четыре вещи, и каждая — про ошибку, которую иначе заметит
    только ученик, увидев чужую работу:

    * страницы внутри книги и в порядке возрастания;
    * куски не перекрываются: одна страница принадлежит одному человеку;
    * один ученик — один кусок. Работа, сшитая из двух мест, бывает, но
      выражается она одним куском, а два куска на человека почти всегда
      значат, что кого-то в списке пропустили;
    * ученик учится в этом курсе.

    Не проверяется намеренно: что разобраны **все** страницы и что каждому
    ученику что-то досталось. Отсутствовавший на контрольной — обычное
    дело, а пустая страница в конце пачки — тем более.
    """
    if not pieces:
        api_error(
            Codes.SPLIT_EMPTY,
            "Nothing is marked up: say which pages belong to whom.",
            field="plan",
        )

    seen_students = set()
    taken = set()

    for piece in pieces:
        if not 1 <= piece.first <= piece.last <= pages:
            api_error(
                Codes.SPLIT_OUT_OF_RANGE,
                f"Pages {piece.first}–{piece.last} are outside the file, "
                f"which has {pages}.",
                field="plan",
                pages=pages,
            )

        overlap = taken & set(piece.pages)
        if overlap:
            api_error(
                Codes.SPLIT_OVERLAP,
                f"Page {min(overlap)} is given to two students at once.",
                field="plan",
                page=min(overlap),
            )
        taken |= set(piece.pages)

        if piece.student_id in seen_students:
            api_error(
                Codes.SPLIT_STUDENT_TWICE,
                "One student is named twice: a work is one piece, however "
                "many sheets it takes.",
                field="plan",
            )
        seen_students.add(piece.student_id)

        if piece.student_id not in students:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That student does not study in this course.",
                field="plan",
            )


def cut_pages(data: bytes, numbers) -> bytes:
    """
    Названные страницы отдельным PDF. Чистая функция: байты в байты.

    Номера идут списком, а не отрезком, и это не общность ради общности:
    разметку руками делают отрезками, а разбор пачки по именам раскладывает
    страницы как попало — один ученик мог взять первый лист и последний.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(data))
    writer = PdfWriter()
    for number in numbers:
        writer.add_page(reader.pages[number - 1])

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def cut(data: bytes, piece: Piece) -> bytes:
    """Один кусок книги отдельным PDF."""
    return cut_pages(data, piece.pages)
