"""
Machine-readable validation errors.

Every user-facing validation failure carries a stable ``code`` next to an
English ``detail``. The frontend looks the code up in its dictionary and
renders a localised message from ``params``; unknown codes fall back to
``detail``, so a new server error never shows up as a blank screen.

Response body::

    {"code": "term_overlap",
     "detail": "Term overlaps with «1st quarter» (1 September — 25 October).",
     "params": {"name": "1st quarter", "start": "2026-09-01", "end": "2026-10-25"},
     "field": "start_date"}

``field`` is optional and only says which input caused the failure.
"""

from rest_framework.exceptions import APIException


class Codes:
    """All error codes in one place: the frontend dictionary mirrors this."""

    # school membership and roles
    NO_SCHOOL = "no_school"
    TEACHERS_ONLY = "teachers_only"
    STUDENTS_ONLY = "students_only"
    PARENTS_ONLY = "parents_only"
    # родитель назвал ребёнка, который не его — или не назвал вовсе, а детей
    # у него несколько, и угадывать тут нечего
    NOT_YOUR_CHILD = "not_your_child"
    CHILD_REQUIRED = "child_required"
    NOT_A_PARENT = "not_a_parent"
    NOT_A_STUDENT = "not_a_student"
    DIFFERENT_SCHOOLS = "different_schools"
    NOT_A_TEACHER_OF_THIS_CHILD = "not_a_teacher_of_this_child"
    BELL_NUMBER_TWICE = "bell_number_twice"
    BELL_ENDS_BEFORE_IT_STARTS = "bell_ends_before_it_starts"
    # Длина школьного дня: сколько уроков в нём и что в него не помещается
    LESSONS_PER_DAY_RANGE = "lessons_per_day_range"
    BELL_BEYOND_DAY = "bell_beyond_day"
    SLOT_NUMBER_BEYOND_DAY = "slot_number_beyond_day"
    EMAIL_OTHER_KIND = "email_other_kind"
    NOT_A_STUDENT = "not_a_student"
    SUPERUSER_REQUIRED = "superuser_required"
    SCHOOL_IN_USE = "school_in_use"
    SCHOOL_ADMIN_REQUIRED = "school_admin_required"
    NOT_COURSE_TEACHER = "not_course_teacher"
    COURSE_TEACHER_TAKEN = "course_teacher_taken"
    COURSE_TEACHER_BUSY = "course_teacher_busy"
    OTHER_SCHOOL = "other_school"
    COURSE_IN_USE = "course_in_use"
    COURSE_NAME_TAKEN = "course_name_taken"
    GRADE_IN_USE = "grade_in_use"
    GRADE_LEVEL_LOCKED = "grade_level_locked"
    GRADE_PRESET_INVALID = "grade_preset_invalid"
    MEMBER_IN_USE = "member_in_use"
    ASSIGNMENT_IN_USE = "assignment_in_use"
    NOT_ASSIGNED = "not_assigned"
    INVITATION_EXISTS = "invitation_exists"
    ALREADY_MEMBER = "already_member"
    LAST_ADMIN = "last_admin"

    # массовый ввод состава курса
    ROSTER_EMPTY = "roster_empty"
    ROSTER_NO_EMAIL = "roster_no_email"
    ROSTER_BAD_EMAIL = "roster_bad_email"
    ROSTER_TWO_EMAILS = "roster_two_emails"
    ROSTER_TOO_MANY_COLUMNS = "roster_too_many_columns"
    ROSTER_TOO_MANY_ROWS = "roster_too_many_rows"

    # school year
    YEAR_DATES_REVERSED = "year_dates_reversed"
    YEAR_NAME_TAKEN = "year_name_taken"
    YEAR_WEEKEND_INVALID = "year_weekend_invalid"
    YEAR_WEEKEND_FULL = "year_weekend_full"
    YEAR_SHRINK_CUTS_EXCEPTIONS = "year_shrink_cuts_exceptions"
    YEAR_SHRINK_CUTS_SLOTS = "year_shrink_cuts_slots"
    YEAR_SHRINK_CUTS_TERMS = "year_shrink_cuts_terms"
    YEAR_SHRINK_CUTS_RECORDS = "year_shrink_cuts_records"
    YEAR_IN_USE = "year_in_use"

    # calendar markup
    EXCEPTION_DATES_REVERSED = "exception_dates_reversed"
    EXCEPTION_OUTSIDE_YEAR = "exception_outside_year"
    EXCEPTION_OVERLAP = "exception_overlap"

    # terms
    TERM_DATES_REVERSED = "term_dates_reversed"
    TERM_OUTSIDE_YEAR = "term_outside_year"
    TERM_OVERLAP = "term_overlap"

    # classes
    CLASS_NAME_TAKEN = "class_name_taken"

    # lesson slots
    SLOT_OUTSIDE_YEAR = "slot_outside_year"
    SLOT_YEAR_MISMATCH = "slot_year_mismatch"
    SLOT_NUMBER_TAKEN = "slot_number_taken"
    SLOT_DUPLICATE = "slot_duplicate"
    SLOT_MOVE_SAME_PLACE = "slot_move_same_place"
    SLOT_LESSON_TAKEN = "slot_lesson_taken"
    SLOT_RECORD_OUT_OF_ORDER = "slot_record_out_of_order"
    SLOT_RECORD_NOT_LAST = "slot_record_not_last"
    SLOT_RECORD_FUTURE = "slot_record_future"
    SLOT_RECORD_NOT_SUGGESTED = "slot_record_not_suggested"
    SLOT_RECORD_NO_ROW = "slot_record_no_row"
    PLAN_LESSON_TAUGHT = "plan_lesson_taught"
    PLAN_BEFORE_TAUGHT = "plan_before_taught"
    PLAN_DELETE_TAUGHT = "plan_delete_taught"
    PLAN_BULK_SECTION = "plan_bulk_section"
    PLAN_NOTHING_TO_UNDO = "plan_nothing_to_undo"
    PLAN_NOTHING_TO_REDO = "plan_nothing_to_redo"
    PLAN_UNDO_WOULD_LOSE_RECORD = "plan_undo_would_lose_record"
    ROWS_INVALID = "rows_invalid"
    SLOT_NOTHING_TO_UNDO = "slot_nothing_to_undo"
    SLOT_UNDO_WOULD_LOSE_WORK = "slot_undo_would_lose_work"
    SLOT_MOVE_BREAKS_ORDER = "slot_move_breaks_order"
    SLOT_MOVE_SERIES_WEEK = "slot_move_series_week"
    SLOT_MOVE_SERIES_RECORDED = "slot_move_series_recorded"
    SLOT_MOVE_SERIES_ONE_OFF = "slot_move_series_one_off"
    SLOT_DELETE_RECORDED = "slot_delete_recorded"
    SLOT_CANCEL_RECORDED = "slot_cancel_recorded"
    SLOT_ORDER_BROKEN = "slot_order_broken"
    PLAN_IMPORT_TAUGHT = "plan_import_taught"
    SLOT_NOT_MINE = "slot_not_mine"

    # bulk operations over the schedule
    PERIOD_REVERSED = "period_reversed"
    PERIOD_REQUIRED = "period_required"
    YEAR_REQUIRED = "year_required"

    # plan library
    NOT_TEMPLATE_AUTHOR = "not_template_author"
    SUBJECT_REQUIRED = "subject_required"
    GRADE_REQUIRED = "grade_required"
    PLAN_EMPTY = "plan_empty"
    TEMPLATE_ROW_UNKNOWN = "template_row_unknown"
    # живой шаблон по предмету и параллели один: второй сделал бы «Обновить»
    # снова двусмысленным, а именно от этого и уходим
    TEMPLATE_ALREADY_LIVE = "template_already_live"
    # снимок не переписывают: он затем и снимок. Передумали — сначала
    # перевесьте пометку, и это видимое действие, а не побочный эффект
    TEMPLATE_IS_A_SNAPSHOT = "template_is_a_snapshot"
    SUBJECT_NAME_TAKEN = "subject_name_taken"
    SUBJECT_IN_USE = "subject_in_use"
    ROOM_IN_USE = "room_in_use"
    HOMEGROUP_TAKEN = "homegroup_taken"
    HOMEGROUP_IN_USE = "homegroup_in_use"
    MODE_INVALID = "mode_invalid"

    # plan tree
    SECTION_INSIDE_SECTION = "section_inside_section"
    PARENT_NOT_SECTION = "parent_not_section"
    PARENT_OTHER_CLASS = "parent_other_class"
    ANCHOR_OTHER_CLASS = "anchor_other_class"
    ANCHOR_OTHER_LEVEL = "anchor_other_level"
    POSITION_TAKEN = "position_taken"
    # чьё дерево правим: у плана два владельца, и назван должен быть ровно
    # один — курс либо шаблон с полки
    PLAN_OWNER_REQUIRED = "plan_owner_required"

    # warnings: not failures, the request goes through
    SLOT_NOT_STUDY_DAY = "slot_not_study_day"
    SLOT_ROOM_BUSY = "slot_room_busy"
    SLOT_STUDENT_BUSY = "slot_student_busy"

    # CSV import
    CLASS_REQUIRED = "class_required"
    FILE_REQUIRED = "file_required"
    FILE_TOO_LARGE = "file_too_large"
    FILE_UNREADABLE = "file_unreadable"
    FILE_TOO_MANY_ROWS = "file_too_many_rows"
    FILE_NOT_XLSX = "file_not_xlsx"
    FILE_NOT_PDF = "file_not_pdf"
    MODE_REQUIRED = "mode_required"

    # CSV: the file is read strictly, and refused whole. There is one format
    # («id,Тема,Урок,Заметка», one row per lesson), so an unreadable row is
    # a mistake to name, not a style to guess at.
    CSV_HEADER_INVALID = "csv_header_invalid"
    CSV_BAD_COLUMNS = "csv_bad_columns"
    CSV_SECTION_ROW = "csv_section_row"
    CSV_ROW_EMPTY = "csv_row_empty"
    CSV_ROW_TOO_LONG = "csv_row_too_long"
    CSV_BAD_ID = "csv_bad_id"
    CSV_ID_UNKNOWN = "csv_id_unknown"
    CSV_ID_DUPLICATE = "csv_id_duplicate"
    CSV_ID_KIND_CHANGED = "csv_id_kind_changed"
    CSV_NOTHING_TO_SYNC = "csv_nothing_to_sync"

    # утверждение плана методистом
    NO_METHODIST = "no_methodist"
    REVIEWER_REQUIRED = "reviewer_required"
    NOT_A_METHODIST = "not_a_methodist"
    COMMENT_REQUIRED = "comment_required"
    REVIEW_CLOSED = "review_closed"
    REVIEW_NOT_PENDING = "review_not_pending"
    BASELINE_UNKNOWN = "baseline_unknown"

    # lesson content and attachments
    CONTENT_ON_SECTION = "content_on_section"
    ATTACHMENT_OWNER_REQUIRED = "attachment_owner_required"
    ATTACHMENT_KIND_MISMATCH = "attachment_kind_mismatch"
    ATTACHMENT_TITLE_REQUIRED = "attachment_title_required"
    ATTACHMENT_FORBIDDEN = "attachment_forbidden"
    ATTACHMENT_NOT_AN_IMAGE = "attachment_not_an_image"
    # Отдельный код от предыдущего, и разошлись они по смыслу: в текст
    # урока встаёт только картинка, а работой ученика бывает и PDF —
    # телефонный сканер отдаёт именно его. Пока код был один, фраза
    # словаря могла быть верной ровно для одного из двух отказов.
    PHOTO_TYPE_NOT_ALLOWED = "photo_type_not_allowed"
    URL_REQUIRED = "url_required"
    # личный стол: у папки нет ничего, кроме имени, и безымянная папка —
    # это строка, по которой не выбрать, куда класть
    FOLDER_TITLE_REQUIRED = "folder_title_required"
    FILE_TYPE_NOT_ALLOWED = "file_type_not_allowed"
    SCHOOL_QUOTA_EXCEEDED = "school_quota_exceeded"
    STORAGE_UNAVAILABLE = "storage_unavailable"

    # работы онлайн
    WORK_NOT_OPEN = "work_not_open"
    WORK_CLOSED = "work_closed"
    NOT_IN_COURSE = "not_in_course"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    WORK_DATES_REVERSED = "work_dates_reversed"
    TASK_QUESTION_REQUIRED = "task_question_required"
    TASK_CLOSED = "task_closed"
    TOO_MANY_CRITERIA = "too_many_criteria"
    SPLIT_EMPTY = "split_empty"
    SPLIT_OUT_OF_RANGE = "split_out_of_range"
    SPLIT_OVERLAP = "split_overlap"
    SPLIT_STUDENT_TWICE = "split_student_twice"
    SPLIT_NOT_IN_COURSE = "split_not_in_course"
    CRITERION_UNKNOWN = "criterion_unknown"
    MARK_OUT_OF_RANGE = "mark_out_of_range"

    # фотографии работы и разметка на них
    TOO_MANY_PHOTOS = "too_many_photos"
    ROTATION_INVALID = "rotation_invalid"
    STROKE_EMPTY = "stroke_empty"
    STROKE_TOO_LONG = "stroke_too_long"
    PEN_WIDTH_INVALID = "pen_width_invalid"
    POINT_INVALID = "point_invalid"
    PAGE_INVALID = "page_invalid"
    COLOUR_INVALID = "colour_invalid"

    # чтение сканов моделью и потолок расхода
    AI_KEY_MISSING = "ai_key_missing"
    AI_BUDGET_EXCEEDED = "ai_budget_exceeded"
    AI_UNAVAILABLE = "ai_unavailable"
    # До модели не достучаться с этого сервера, и заменить её некем. Отдельно
    # от AI_KEY_MISSING нарочно: там нечем звать, здесь — некуда дозвониться,
    # и чинятся эти два совершенно по-разному.
    AI_UNREACHABLE = "ai_unreachable"
    # Читатель есть, но промолчал. Не то же, что «читателя нет»: повторить
    # имеет смысл, а настраивать нечего.
    SCAN_READER_SILENT = "scan_reader_silent"
    AI_LIMIT_NEGATIVE = "ai_limit_negative"
    SCAN_PAGE_UNKNOWN = "scan_page_unknown"
    SCAN_NOTHING_READ = "scan_nothing_read"

    # банк задач
    BANK_READ_ONLY = "bank_read_only"
    OUTLINE_JUMP = "outline_jump"
    OUTLINE_EMPTY = "outline_empty"
    PROBLEM_TEXT_REQUIRED = "problem_text_required"
    PART_WITHOUT_NUMBER = "part_without_number"
    NUMBER_NEEDS_A_TAB = "number_needs_a_tab"
    TAG_KIND_MISMATCH = "tag_kind_mismatch"
    TAG_NOT_NEGATABLE = "tag_not_negatable"
    SUPERUSER_ONLY_TAGS = "superuser_only_tags"
    BANK_EXPRESSION_BAD = "bank_expression_bad"
    BANK_SAME_PROBLEM = "bank_same_problem"
    BANK_NOTHING_TO_COPY = "bank_nothing_to_copy"
    PROPOSAL_EMPTY = "proposal_empty"
    PROPOSAL_ANSWER_REQUIRED = "proposal_answer_required"
    TAG_KIND_REQUIRED = "tag_kind_required"
    WORK_NOTHING_TO_ASSEMBLE = "work_nothing_to_assemble"
    STATEMENT_MODE_UNKNOWN = "statement_mode_unknown"
    STEM_IS_NOT_A_QUESTION = "stem_is_not_a_question"
    SEARCH_NAME_REQUIRED = "search_name_required"

    # разговор о задаче
    MESSAGE_EMPTY = "message_empty"

    # системы оценивания
    GRADING_NAME_REQUIRED = "grading_name_required"
    GRADING_NAME_TAKEN = "grading_name_taken"

    # виды работ
    WORK_KIND_NAME_REQUIRED = "work_kind_name_required"
    WORK_KIND_NAME_TAKEN = "work_kind_name_taken"
    WORK_KIND_LABEL_REQUIRED = "work_kind_label_required"

    # sign-in
    TOKEN_REQUIRED = "token_required"
    TOKEN_INVALID = "token_invalid"
    EMAIL_NOT_VERIFIED = "email_not_verified"
    # контур пускает не всех: список допущенных адресов задан, и этого в
    # нём нет. Не «неверный пароль» и не «нет учётки» — сюда просто не вам
    NOT_ALLOWED_HERE = "not_allowed_here"


def error_payload(code: str, detail: str, *, field: str | None = None, **params) -> dict:
    """Build the body of a coded validation error."""
    payload = {"code": code, "detail": detail}
    if params:
        payload["params"] = params
    if field:
        payload["field"] = field
    return payload


class ApiError(APIException):
    """
    A coded failure, rendered as the payload and nothing else.

    Deliberately not a DRF ``ValidationError``: raising one inside
    ``validate()`` sends it through ``as_serializer_error``, which treats the
    body as a field→errors mapping and wraps every value in a list — the
    payload would arrive as ``{"code": ["term_overlap"]}``. This one flies
    straight to the exception handler, so ``params`` keep their own types too.
    """

    status_code = 400

    def __init__(self, payload: dict, status_code: int | None = None):
        self.detail = payload
        if status_code is not None:
            self.status_code = status_code


def api_error(code: str, detail: str, *, field: str | None = None, **params):
    """Raise a coded validation error (HTTP 400)."""
    raise ApiError(error_payload(code, detail, field=field, **params))


def api_unavailable(code: str, detail: str, **params):
    """
    Raise a coded "not now" (HTTP 503).

    Kept apart from `api_error` on purpose: a file store that is down is not
    a mistake the person made, and retyping will not help. The interface says
    "try again later" instead of pointing at a field.
    """
    raise ApiError(error_payload(code, detail, **params), status_code=503)


def api_denied(code: str, detail: str, **params):
    """
    Raise a coded refusal (HTTP 403).

    Same shape as a validation error, so the frontend reads both through one
    dictionary — a refusal is just an error retyping cannot fix.
    """
    raise ApiError(error_payload(code, detail), status_code=403)
