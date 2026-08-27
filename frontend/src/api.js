import { childParam, viewedChild } from './viewedChild'
import i18n from './i18n'

const TOKEN_KEY = 'authToken'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

class ApiError extends Error {
  constructor(message, status, code = null, params = null) {
    super(message)
    this.status = status
    // the machine-readable half of the answer, kept for callers that branch
    // on the code instead of showing the text
    this.code = code
    this.params = params
  }
}

/**
 * The message a person should see.
 *
 * The backend answers with a code, an English detail and params; the code is
 * looked up in the dictionary and an unknown one falls back to the detail, so
 * a server error added tomorrow still arrives readable today.
 */
function humanMessage(data) {
  if (data?.code) {
    return i18n.t(`errors.${data.code}`, {
      defaultValue: data.detail || i18n.t('errors.unknown'),
      ...(data.params || {}),
    })
  }

  // plain DRF answers: either detail or field errors
  const fieldError =
    data && typeof data === 'object' ? Object.values(data).flat()[0] : null
  return data?.detail || fieldError || i18n.t('errors.unknown')
}

async function request(path, { method = 'GET', body, auth = true, as } = {}) {
  const headers = {}
  // FormData has its own Content-Type with a boundary; the browser sets it
  const isForm = body instanceof FormData
  if (body && !isForm) headers['Content-Type'] = 'application/json'

  // `as` — запрос от имени не того, кем мы сейчас ходим. Нужен ровно
  // переключателю «войти как» на стенде: подменившись учеником, вернуться
  // и переключиться дальше он должен **своим** токеном, а текущий уже
  // ученический. Обычные вызовы про это не знают и берут токен из хранилища.
  const token = as ?? getToken()
  if (auth && token) headers['Authorization'] = `Token ${token}`

  /*
   * Сеть не ответила — это не «ошибка приложения», и звучать должна иначе.
   *
   * `fetch` в этом случае бросает `TypeError: Failed to fetch` — строку, в
   * которой человеку нет ничего: ни что произошло, ни что делать. А
   * происходит это буднично: пропал интернет, уснул ноутбук, или сервер
   * перезапускают выкаткой — последнее поймано на проде, `Failed to fetch`
   * посреди работы, в английском виде и в русском интерфейсе.
   *
   * Статуса у такого отказа нет по построению (ответа не было вовсе),
   * поэтому 0: вызывающий код смотрит на 401 и на коды ошибок, и ни одно
   * из его правил ноль не задевает.
   */
  let response
  try {
    // Vite proxies /api to backend:8000, so the path stays relative
    response = await fetch(path, {
      method,
      headers,
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
    })
  } catch {
    throw new ApiError(i18n.t('errors.offline'), 0, 'offline', null)
  }

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    throw new ApiError(
      humanMessage(data),
      response.status,
      data?.code ?? null,
      data?.params ?? null,
    )
  }

  return data
}

export const loginWithGoogle = (idToken) =>
  request('/api/auth/google/', {
    method: 'POST',
    body: { id_token: idToken },
    auth: false,
  })

export const fetchMe = () => request('/api/me/')

export const updateMe = (fields) =>
  request('/api/me/', { method: 'PATCH', body: fields })

export const logout = () => request('/api/auth/logout/', { method: 'POST' })

// --- onboarding ---

export const fetchOnboarding = () => request('/api/onboarding/status/')

export const createDemoData = () =>
  request('/api/onboarding/demo/', { method: 'POST' })

// --- school years and the calendar ---

export const fetchSchoolYears = () => request('/api/calendar/years/')

export const fetchSchoolYear = (id) => request(`/api/calendar/years/${id}/`)

export const createSchoolYear = (fields) =>
  request('/api/calendar/years/', { method: 'POST', body: fields })

export const deleteSchoolYear = (id) =>
  request(`/api/calendar/years/${id}/`, { method: 'DELETE' })

// что стоит на годе: спрашиваем до удаления, потому что каскад уносит
// курсы и школьное расписание, а не только разметку календаря
export const fetchYearUsage = (id) => request(`/api/calendar/years/${id}/usage/`)

export const fetchYearDays = (id) => request(`/api/calendar/years/${id}/days/`)

export const fetchYearStats = (id) => request(`/api/calendar/years/${id}/stats/`)

export const fetchTerms = (yearId) =>
  request(`/api/calendar/terms/?year=${encodeURIComponent(yearId)}`)

export const createTerm = (fields) =>
  request('/api/calendar/terms/', { method: 'POST', body: fields })

export const updateTerm = (id, fields) =>
  request(`/api/calendar/terms/${id}/`, { method: 'PATCH', body: fields })

export const deleteTerm = (id) =>
  request(`/api/calendar/terms/${id}/`, { method: 'DELETE' })

export const createException = (fields) =>
  request('/api/calendar/exceptions/', { method: 'POST', body: fields })

/**
 * Чем план отличается от эталона — построчно.
 *
 * Без версии сравнение идёт с последним утверждением; их у курса за год
 * несколько, и «что изменилось с начала года» — такой же вопрос.
 */
export const fetchPlanDiff = (classId, baseline) =>
  request(
    `/api/plan/diff/?course=${encodeURIComponent(classId)}` +
      (baseline ? `&baseline=${encodeURIComponent(baseline)}` : ''),
  )

/** Переименование пометки: у праздника и каникул своё имя, и его правят. */
export const updateException = (id, fields) =>
  request(`/api/calendar/exceptions/${id}/`, { method: 'PATCH', body: fields })

export const deleteException = (id) =>
  request(`/api/calendar/exceptions/${id}/`, { method: 'DELETE' })

// --- the school: courses, people, invitations ---

/**
 * Courses. By default the ones this teacher was given.
 *
 * `scope: 'school'` asks for the whole list instead — that is what the
 * «School» section manages, including the courses nobody teaches yet.
 * Without a year: every course, which the agenda needs.
 */
export const fetchCourses = (yearId, { scope } = {}) => {
  const query = new URLSearchParams()
  if (yearId) query.set('year', yearId)
  if (scope) query.set('scope', scope)
  const tail = query.toString()

  return request(tail ? `/api/courses/?${tail}` : '/api/courses/')
}

// the three below answer 403 «school_admin_required» for a plain teacher —
// the interface hides the buttons, the server is what actually refuses
export const createCourse = (fields) =>
  request('/api/courses/', { method: 'POST', body: fields })

export const renameCourse = (id, name) =>
  request(`/api/courses/${id}/`, { method: 'PATCH', body: { name } })

export const deleteCourse = (id) =>
  request(`/api/courses/${id}/`, { method: 'DELETE' })

export const renameMySchool = (name) =>
  request('/api/school/', { method: 'PATCH', body: { name } })

// --- every school at once: superuser only ---

export const fetchSchools = () => request('/api/schools/')

export const createSchool = (name) =>
  request('/api/schools/', { method: 'POST', body: { name } })

export const renameSchool = (id, name) =>
  request(`/api/schools/${id}/`, { method: 'PATCH', body: { name } })

export const deleteSchool = (id) =>
  request(`/api/schools/${id}/`, { method: 'DELETE' })

/** Invite the first administrator of a school that has none yet. */
export const inviteSchoolAdmin = (id, email) =>
  request(`/api/schools/${id}/invite/`, { method: 'POST', body: { email } })

export const fetchMembers = (params = {}) =>
  request(`/api/school/members/?${new URLSearchParams(params)}`)

export const setMemberRole = (id, isAdmin) =>
  request(`/api/school/members/${id}/`, {
    method: 'PATCH',
    body: { is_school_admin: isAdmin },
  })

export const fetchInvitations = (params = {}) =>
  request(`/api/school/invitations/?${new URLSearchParams(params)}`)

export const createInvitation = (fields) =>
  request('/api/school/invitations/', { method: 'POST', body: fields })

export const deleteInvitation = (id) =>
  request(`/api/school/invitations/${id}/`, { method: 'DELETE' })

/**
 * Detach a teacher from the school. Their lessons are kept; the plan
 * belongs to the course and stays there.
 *
 * Refused the first time with the counts, exactly like unassigning: `force`
 * is the confirmation, and the interface only sends it after the person has
 * read what the counts are.
 */
export const detachMember = (id, { force = false } = {}) =>
  request(`/api/school/members/${id}/${force ? '?force=true' : ''}`, {
    method: 'DELETE',
  })

// --- the school's state in one number each ---

export const fetchSchoolOverview = () => request('/api/school/overview/')

// --- reference lists: subjects and year groups ---

export const fetchGrades = () => request('/api/school/grades/')

export const createGrade = (fields) =>
  request('/api/school/grades/', { method: 'POST', body: fields })

export const updateGrade = (id, fields) =>
  request(`/api/school/grades/${id}/`, { method: 'PATCH', body: fields })

export const deleteGrade = (id) =>
  request(`/api/school/grades/${id}/`, { method: 'DELETE' })

/** Fill the list with years 1..N. Existing ones are left as they are. */
export const addGradePreset = (through) =>
  request('/api/school/grades/preset/', { method: 'POST', body: { through } })

/** Drop every year group no course points at. */
export const clearUnusedGrades = () =>
  request('/api/school/grades/unused/', { method: 'DELETE' })

export const renameSubject = (id, name) =>
  request(`/api/school/subjects/${id}/`, { method: 'PATCH', body: { name } })

export const deleteSubject = (id) =>
  request(`/api/school/subjects/${id}/`, { method: 'DELETE' })

// --- who teaches what: written from both the teacher and the course ---

export const fetchAssignments = (params = {}) =>
  request(`/api/school/assignments/?${new URLSearchParams(params)}`)

export const createAssignment = (course, teacher) =>
  request('/api/school/assignments/', {
    method: 'POST',
    body: { course, teacher },
  })

/** Unassigning keeps the lessons and the plan; `force` confirms that. */
export const deleteAssignment = (id, { force = false } = {}) =>
  request(`/api/school/assignments/${id}/${force ? '?force=true' : ''}`, {
    method: 'DELETE',
  })

// --- the plan library: templates shared inside the school ---

export const fetchTemplates = (params = {}) =>
  request(`/api/library/templates/?${new URLSearchParams(params)}`)

export const fetchTemplate = (id) => request(`/api/library/templates/${id}/`)

export const updateTemplate = (id, fields) =>
  request(`/api/library/templates/${id}/`, { method: 'PATCH', body: fields })

export const deleteTemplate = (id) =>
  request(`/api/library/templates/${id}/`, { method: 'DELETE' })

/** Put the plan of a course on the shelf. Starts as the author's draft. */
export const publishPlan = (fields) =>
  request('/api/library/templates/from-plan/', { method: 'POST', body: fields })

/** Refresh a shelf entry from a course plan. Nobody who copied is affected. */
export const refreshTemplate = (id, courseId) =>
  request(`/api/library/templates/${id}/update-from-plan/`, {
    method: 'POST',
    body: { course: courseId },
  })

/**
 * Вести дальше **этот** шаблон, а не прежний.
 *
 * Одно действие на две записи: пометка снимается с прежнего живого и
 * ставится сюда. Двумя запросами это было бы состояние «живых два» между
 * ними, а его не пустит ограничение базы.
 */
export const keepUpdatingTemplate = (id) =>
  request(`/api/library/templates/${id}/keep-updating/`, { method: 'POST' })

/** Take a template into a course plan — a copy, not a link. */
export const importTemplate = (payload) =>
  request('/api/plan/import-from-template/', { method: 'POST', body: payload })

export const fetchSubjects = () => request('/api/school/subjects/')

// --- кабинеты: справочник школы, живёт рядом с расписанием ---

export const fetchRooms = () => request('/api/rooms/')

export const createRoom = (fields) =>
  request('/api/rooms/', { method: 'POST', body: fields })

export const updateRoom = (id, fields) =>
  request(`/api/rooms/${id}/`, { method: 'PATCH', body: fields })

export const deleteRoom = (id) => request(`/api/rooms/${id}/`, { method: 'DELETE' })

// --- классы (хоумрумы): состав выводит связь курса с классом ---

export const fetchHomegroups = (params = {}) =>
  request(`/api/homegroups/?${new URLSearchParams(params)}`)

export const createHomegroup = (fields) =>
  request('/api/homegroups/', { method: 'POST', body: fields })

export const updateHomegroup = (id, fields) =>
  request(`/api/homegroups/${id}/`, { method: 'PATCH', body: fields })

export const deleteHomegroup = (id) =>
  request(`/api/homegroups/${id}/`, { method: 'DELETE' })

// без параметра — все действующие строки школы: экран «Ученики» показывает
// класс у каждого, и спрашивать по классу значило бы спросить десять раз
export const fetchHomegroupStudents = (params = {}) =>
  request(`/api/homegroup-students/?${new URLSearchParams(params)}`)

export const addHomegroupStudent = (homegroup, student) =>
  request('/api/homegroup-students/', {
    method: 'POST',
    body: { homegroup, student },
  })

// снятие, а не удаление: где человек учился, остаётся правдой
export const removeHomegroupStudent = (id) =>
  request(`/api/homegroup-students/${id}/`, { method: 'DELETE' })

export const createSubject = (name) =>
  request('/api/school/subjects/', { method: 'POST', body: { name } })

// --- the lesson plan ---

/**
 * Лента слотов курса: даты, термы и каникулы между уроками.
 *
 * Берётся один раз на курс — от плана она не зависит, а сшивает их
 * страница у себя (`planLayout.js`), чтобы даты сдвигались мгновенно.
 */
export const fetchPlanSlots = (classId) =>
  request(`/api/plan/layout/slots/?course=${encodeURIComponent(classId)}`)

export const fetchPlan = (classId) =>
  request(`/api/plan/?course=${encodeURIComponent(classId)}`)

export const createPlanNode = (fields) =>
  request('/api/plan/', { method: 'POST', body: fields })

// тема сразу за этой строкой; внутри темы это разрез — хвост уезжает в новую
// то же сравнение глазами методиста: границу доступа держит сам запрос
export const fetchReviewDiff = (courseId, baseline) =>
  request(
    `/api/plan/reviews/${courseId}/diff/` +
      (baseline ? `?baseline=${encodeURIComponent(baseline)}` : ''),
  )

export const splitPlan = (id, title) =>
  request(`/api/plan/${id}/split/`, { method: 'POST', body: { title } })

export const updatePlanNode = (id, fields) =>
  request(`/api/plan/${id}/`, { method: 'PATCH', body: fields })

export const deletePlanNode = (id, keepChildren) =>
  request(`/api/plan/${id}/?keep_children=${keepChildren ? 'true' : 'false'}`, {
    method: 'DELETE',
  })

/**
 * Удалить пачку строк — одним запросом и одной транзакцией.
 *
 * Не десять запросов подряд: половина удалённой пачки хуже неудалённой,
 * потому что непонятно, какая половина. Отказ на любой строке отменяет всё.
 */
export const deletePlanNodes = (courseId, ids) =>
  request(`/api/plan/delete/?course=${courseId}`, {
    method: 'POST',
    body: { ids },
  })

/**
 * Чем можно отменить: снимки плана, свежие первыми.
 *
 * Приезжают вместе с деревом, а не по кнопке: кнопка отмены обязана
 * называть, что именно отменит, — значит знать это надо до нажатия.
 */
export const fetchPlanHistory = (courseId) =>
  request(`/api/plan/history/?course=${courseId}`)

/** Вернуть план к снимку; без номера — к последнему. */
export const undoPlan = (courseId, snapshot = null) =>
  request(`/api/plan/undo/?course=${courseId}`, {
    method: 'POST',
    body: snapshot ? { snapshot } : {},
  })

const csvForm = (file, mode) => {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)
  return form
}

/** Куда слать файл: книгу читает openpyxl на сервере, CSV — свой разбор. */
const isWorkbook = (file) => /\.xlsx$/i.test(file?.name ?? '')

export const importPlanFile = (classId, file, mode) =>
  request(
    `/api/plan/${isWorkbook(file) ? 'import-xlsx' : 'import'}/` +
      `?course=${encodeURIComponent(classId)}`,
    { method: 'POST', body: csvForm(file, mode) },
  )

/**
 * What the import would do — counts, and what would be lost.
 *
 * Asked of the server rather than worked out here: only it knows which
 * lessons have content, and which files nothing else points at.
 */
export const previewPlanFile = (classId, file, mode) =>
  request(
    `/api/plan/${isWorkbook(file) ? 'import-preview-xlsx' : 'import-preview'}/` +
      `?course=${encodeURIComponent(classId)}`,
    { method: 'POST', body: csvForm(file, mode) },
  )

/**
 * Вставка из таблицы: те же строки, только приехали не файлом.
 *
 * Табуляции и кавычки разобрал браузер, сюда едет матрица ячеек — сервер
 * читает её тем же кодом, что ячейки книги.
 */
export const importPlanRows = (classId, rows, mode) =>
  request(`/api/plan/import-rows/?course=${encodeURIComponent(classId)}`, {
    method: 'POST',
    body: { rows, mode },
  })

export const previewPlanRows = (classId, rows, mode) =>
  request(`/api/plan/import-preview-rows/?course=${encodeURIComponent(classId)}`, {
    method: 'POST',
    body: { rows, mode },
  })

/**
 * Downloading the plan.
 *
 * A plain link will not do: the endpoint wants a token in the header, so the
 * file is fetched and handed to the browser as a blob.
 *
 * Адреса два, а работа одна. Свой план выгружается со страницы плана, чужой
 * — с экрана чужого плана, и ходят они в разные ручки: у автора курс в
 * `?course=`, у читателя — в пути, потому что и право там другое. Всё
 * остальное — заголовок с токеном, разбор имени файла, blob — совпадает
 * целиком, и вторая копия этого разошлась бы с первой на первой же правке.
 */
export const downloadPlan = async (
  classId,
  format = 'xlsx',
  { foreign = false, dates = false } = {},
) => {
  const token = getToken()
  const path = format === 'xlsx' ? 'export-xlsx' : 'export'
  // `dates` — вопрос запроса, а не настройки: тот же файл с объявленным
  // четвёртым столбцом, который импорт принимает и отбрасывает
  const query = new URLSearchParams(foreign ? {} : { course: classId })
  if (dates) query.set('dates', '1')
  const suffix = query.toString() ? `?${query}` : ''
  const address = foreign
    ? `/api/plan/reviews/${encodeURIComponent(classId)}/${path}/${suffix}`
    : `/api/plan/${path}/${suffix}`
  const response = await fetch(address, {
    headers: token ? { Authorization: `Token ${token}` } : {},
  })

  if (!response.ok) {
    throw new ApiError(i18n.t('errors.downloadFailed'), response.status)
  }

  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const name = encoded ? decodeURIComponent(encoded[1]) : `plan.${format}`

  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// --- one lesson: content and attachments ---

/** The whole of one lesson, content included — the tree only carries flags. */
export const fetchPlanNode = (id) => request(`/api/plan/${id}/`)

export const uploadAttachment = ({
  planRow,
  templateRow,
  studentWork,
  // сама работа: условия pdf'ом и картинка в пояснениях. Не путать с
  // `studentWork` — то тетрадь одного человека, а это задание на весь класс
  work,
  file,
  title,
  inline = false,
  // видно ли это классу. Едет **с загрузкой**, а не выставляется следом:
  // приложенные видимыми ответы к контрольной успевают побывать открытыми
  staffOnly = false,
}) => {
  const form = new FormData()
  if (planRow) form.append('plan_row', planRow)
  if (templateRow) form.append('template_row', templateRow)
  if (studentWork) form.append('student_work', studentWork)
  if (work) form.append('work', work)
  form.append('file', file)
  if (title) form.append('title', title)
  // «эта картинка встала в текст»: в списке материалов её не будет, и
  // распоряжается ею содержание, а не список
  if (inline) form.append('inline', 'true')
  if (staffOnly) form.append('staff_only', 'true')

  return request('/api/attachments/', { method: 'POST', body: form })
}

/**
 * Передумать: показать классу спрятанное или спрятать показанное.
 *
 * Отдельным запросом, а не пересозданием вложения: файл в бакете тот же, и
 * заново возить его ради одного признака значило бы платить местом за
 * передуманное решение.
 */
export const setAttachmentVisibility = (id, staffOnly) =>
  request(`/api/attachments/${id}/`, {
    method: 'PATCH',
    body: { staff_only: staffOnly },
  })

/** Материал, у которого нет ни файла, ни адреса: «Мордкович, §14». */
export const addTextAttachment = ({ planRow, templateRow, title }) =>
  request('/api/attachments/', {
    method: 'POST',
    body: {
      ...(planRow ? { plan_row: planRow } : { template_row: templateRow }),
      kind: 'text',
      title,
    },
  })

export const addLinkAttachment = ({ planRow, templateRow, url, title }) =>
  request('/api/attachments/', {
    method: 'POST',
    body: {
      ...(planRow ? { plan_row: planRow } : { template_row: templateRow }),
      url,
      title,
    },
  })

export const deleteAttachment = (id) =>
  request(`/api/attachments/${id}/`, { method: 'DELETE' })

/**
 * Download a file.
 *
 * Two steps rather than following the endpoint's redirect: the request needs
 * an Authorization header, and a header does not survive a redirect to
 * another origin. So the address is asked for as JSON and the browser is
 * pointed at it — the response carries Content-Disposition: attachment, so
 * the page stays where it is and the file arrives.
 */
export const openAttachment = async (id) => {
  const { url } = await request(`/api/attachments/${id}/download/?json=1`)
  window.location.assign(url)
}

/**
 * Адрес картинки, стоящей в содержании урока.
 *
 * Спрашивается по объекту в бакете, а не по вложению: разметка называет
 * файл, потому что он один на все копии плана (`imageMarkdown.js`). Ответ
 * подписан на пять минут, и `<img>` берёт его в `src` — заголовок с токеном
 * картинка нести не умеет, поэтому за адресом ходит страница.
 */
export const fetchImageUrl = (fileId) => request(`/api/images/${fileId}/`)

/**
 * Как идут дела по всем курсам сразу — страница «Раскладка».
 *
 * Один запрос на страницу и ни одного расчёта на клиенте: числа считает тот
 * же код, что и остальные ответы про раскладку, поэтому разойтись с планом
 * они не могут.
 */

/**
 * Состояние эталона у плана курса: утверждённое, поданное и кому слать.
 *
 * Один запрос на весь блок: иначе страница показывала бы полусостояние —
 * «на утверждении», пока список методистов ещё едет.
 */
export const fetchBaseline = (classId) =>
  request(`/api/plan/baseline/?course=${encodeURIComponent(classId)}`)

/** Отправить план на утверждение — снимок снимается в этот момент. */
export const submitBaseline = (classId, reviewer) =>
  request(`/api/plan/baseline/submit/?course=${encodeURIComponent(classId)}`, {
    method: 'POST',
    body: reviewer ? { reviewer } : {},
  })

// --- работы: контрольные, проверочные, домашние ---
//
// У учителя своя половина (сами работы и задачи), у ученика своя (что
// открыто и что он ответил). Адреса разные, потому что и вопросы разные.

export const fetchWorks = (course) =>
  request(`/api/works/?course=${course}`)

/** Одна работа целиком — страница правки открывается по адресу, без списка. */
export const fetchWork = (id) => request(`/api/works/${id}/`)

export const createWork = (fields) =>
  request('/api/works/', { method: 'POST', body: fields })

export const updateWork = (id, fields) =>
  request(`/api/works/${id}/`, { method: 'PATCH', body: fields })

export const deleteWork = (id) => request(`/api/works/${id}/`, { method: 'DELETE' })

/** Что стоит за работой прямо сейчас: сколько ответов и проверок. */
export const fetchWorkImpact = (id) => request(`/api/works/${id}/impact/`)

/**
 * Сводная таблица работы. `version` делает опрос дешёвым: совпала — сервер
 * отвечает «не изменилось» и не собирает триста ячеек.
 */
/** Шкала работы: список критериев. Пустой — работа не оценивается. */
export const fetchScale = (work) => request(`/api/works/${work}/criteria/`)

export const saveScale = (work, criteria) =>
  request(`/api/works/${work}/criteria/`, { method: 'PUT', body: { criteria } })

/** Сколько оценок потеряет правка шкалы — спрашивается до нажатия. */
export const fetchScaleImpact = (work) =>
  request(`/api/works/${work}/scale_impact/`)

/**
 * Разобрать один скан на работы учеников.
 *
 * Разметка едет строкой JSON рядом с файлом: форма multipart вложенных
 * структур не выражает, и это единственная причина.
 */
/* --- разбор пачки сканов ------------------------------------------------- */

/* --- банк задач ------------------------------------------------------------ */

export const fetchSources = (subject) =>
  request(`/api/bank/sources/${subject ? `?subject=${subject}` : ''}`)

export const createSource = (fields) =>
  request('/api/bank/sources/', { method: 'POST', body: fields })

export const fetchSource = (id, params = {}) => {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== null && value !== ''),
  ).toString()
  return request(`/api/bank/sources/${id}/${query ? `?${query}` : ''}`)
}

export const fillSource = (id, body) =>
  request(`/api/bank/sources/${id}/`, { method: 'POST', body })

export const fetchProblem = (id) => request(`/api/bank/problems/${id}/`)

export const saveProblem = (id, fields) =>
  request(`/api/bank/problems/${id}/`, { method: 'PATCH', body: fields })

export const createSolution = (fields) =>
  request('/api/bank/solutions/', { method: 'POST', body: fields })

export const saveSolution = (fields) =>
  request('/api/bank/solutions/', { method: 'PATCH', body: fields })

export const fetchTags = (kind) =>
  request(`/api/bank/tags/${kind ? `?kind=${kind}` : ''}`)

export const createTag = (fields) =>
  request('/api/bank/tags/', { method: 'POST', body: fields })

export const linkTag = (body) =>
  request('/api/bank/tag-links/', { method: 'POST', body })

export const unlinkTag = (body) =>
  request('/api/bank/tag-links/', { method: 'DELETE', body })

/* --- системы оценивания и разговор о задаче ------------------------------- */

export const fetchGradingSystems = () => request('/api/works/grading/')

export const addTypicalGrading = () =>
  request('/api/works/grading/', { method: 'POST', body: { typical: true } })

export const createGradingSystem = (fields) =>
  request('/api/works/grading/', { method: 'POST', body: fields })

export const saveGradingSystem = (id, fields) =>
  request(`/api/works/grading/${id}/`, { method: 'PATCH', body: fields })

export const deleteGradingSystem = (id) =>
  request(`/api/works/grading/${id}/`, { method: 'DELETE' })

/* Виды работ — справочник школы той же формы, что и системы оценивания:
   читают все учителя, правит администратор. */
export const fetchWorkKinds = () => request('/api/works/kinds/')

export const addTypicalKinds = () =>
  request('/api/works/kinds/', { method: 'POST', body: { typical: true } })

export const createWorkKind = (fields) =>
  request('/api/works/kinds/', { method: 'POST', body: fields })

export const saveWorkKind = (id, fields) =>
  request(`/api/works/kinds/${id}/`, { method: 'PATCH', body: fields })

export const deleteWorkKind = (id) =>
  request(`/api/works/kinds/${id}/`, { method: 'DELETE' })

export const fetchThread = (task, student) =>
  request(`/api/works/thread/?task=${task}${student ? `&student=${student}` : ''}`)

export const sendToThread = (task, student, text) =>
  request(`/api/works/thread/?task=${task}${student ? `&student=${student}` : ''}`, {
    method: 'POST',
    body: { text },
  })

export const fetchQuestions = (work) => request(`/api/works/${work}/questions/`)

export const saveQuestions = (work, questions) =>
  request(`/api/works/${work}/questions/`, { method: 'PUT', body: { questions } })

export const fetchScanState = (work) => request(`/api/works/${work}/scan/state/`)

export const resetScan = (work) =>
  request(`/api/works/${work}/scan/state/`, { method: 'DELETE' })

export const readScanPage = (
  work,
  { index, blob, plain, mark, second = true, reader = '' },
) => {
  const form = new FormData()
  form.append('index', index)
  form.append('strip', blob, `strip-${index}.jpg`)
  // Та же шапка как на бумаге. По ней читают имя: распознаватель на собранном
  // листе склеивает строку имени с первым рядом плиток. Необязательна — без
  // неё читают по собранному листу, как читали раньше.
  if (plain) form.append('plain', plain, `plain-${index}.jpg`)
  form.append('fingerprint', mark)
  // Звать ли поверх первого читателя Mathpix. Решение принимается один раз на
  // пачку — на шаге выбора файла, — а ехать ему приходится с каждой страницей:
  // цикл чтения ведёт браузер, и другого места у просьбы нет.
  form.append('second', second ? 'true' : 'false')
  // Кем читать имя — тем же путём и по той же причине. Пустая строка значит
  // «кем умеете»: контур возьмёт первого доступного сам.
  form.append('reader', reader)
  return request(`/api/works/${work}/scan/read/`, { method: 'POST', body: form })
}

export const markHeaderless = (work, index, ours) =>
  request(`/api/works/${work}/scan/page/`, {
    method: 'POST',
    body: { index, headerless: true, ours },
  })

export const editScanPage = (work, fields) =>
  request(`/api/works/${work}/scan/page/`, { method: 'POST', body: fields })

export const readScanQuestions = (work, blob) => {
  const form = new FormData()
  form.append('sheet', blob, 'sheet.jpg')
  return request(`/api/works/${work}/scan/questions/`, { method: 'POST', body: form })
}

export const applyScan = (work, file) => {
  const form = new FormData()
  form.append('file', file)
  return request(`/api/works/${work}/scan/apply/`, { method: 'POST', body: form })
}

/**
 * Взять приложенную к работе пачку обратно — файлом, как будто её выбрали.
 *
 * Мастеру нужен не адрес, а сам PDF: страницы рисует браузер, полоски режет
 * он же, и на применение файл уезжает целиком. Поэтому подписанная ссылка
 * тут же и скачивается, а наружу отдаётся `File` — тот самый объект, который
 * до сих пор приходил из поля выбора файла. Ниже по течению про разницу
 * «выбрали руками» и «взяли с сервера» не знает никто, и знать не должен.
 *
 * Ходит запрос **не** через `request`: адрес чужой (бакет), и заголовок с
 * нашим токеном там не нужен и вреден — подпись в самой ссылке.
 */
export const fetchScanBatch = async (id, name = 'scan.pdf') => {
  const url = await photoUrl(id)
  const answer = await fetch(url)
  if (!answer.ok) throw new ApiError(i18n.t('errors.downloadFailed'), answer.status)
  return new File([await answer.blob()], name, { type: 'application/pdf' })
}

/**
 * Журнал курса: ученики по строкам, занятия по столбцам.
 *
 * `term` — номер четверти, `'all'` для года целиком или `null`. Последнее не
 * «без терма», а «решай сам»: сервер открывает ту четверть, в которой идёт
 * сегодняшний день, и знает он это лучше браузера — часы у них разные, а
 * границы четвертей лежат в базе.
 */
export const fetchJournal = (course, term = null) =>
  request(
    `/api/works/journal/?course=${course}${term === null ? '' : `&term=${term}`}`,
  )

export const fetchAiBudget = () => request('/api/school/ai-budget/')

export const saveAiBudget = (cents) =>
  request('/api/school/ai-budget/', { method: 'PATCH', body: { limit_cents: cents } })

export const fetchAiSpend = (mine) =>
  request(`/api/school/ai-spend/${mine ? '?mine=true' : ''}`)

export const splitScan = (work, { file, plan }) => {
  const form = new FormData()
  form.append('file', file)
  form.append('plan', JSON.stringify(plan))

  return request(`/api/works/${work}/split/`, { method: 'POST', body: form })
}

/** Переложить работу тому, чья она: ошибку разбора надо чинить одним движением. */
export const reassignPaper = (work, attachment, student) =>
  request(`/api/works/${work}/reassign/`, {
    method: 'POST',
    body: { attachment, student },
  })

/** Оценка одного ученика: весь набор критериев и слова учителя за раз. */
export const gradeStudent = (work, body) =>
  request(`/api/works/${work}/grade/`, { method: 'POST', body })

export const fetchWorkTable = (id, version) =>
  request(`/api/works/${id}/table/${version ? `?version=${encodeURIComponent(version)}` : ''}`)

/** Журнал ячейки или всего столбца: те же отправки, разный фильтр. */
export const fetchSubmissions = (params) =>
  request(`/api/works/submissions/?${new URLSearchParams(params)}`)

/** Отметка. `null` — снять: попытку это не расходует, журнал не трогает. */
export const setMark = (id, value) =>
  request(`/api/works/submissions/${id}/`, {
    method: 'PATCH',
    body: { mark: value },
  })

export const fetchTasks = (work) => request(`/api/works/tasks/?work=${work}`)

export const createTask = (fields) =>
  request('/api/works/tasks/', { method: 'POST', body: fields })

export const updateTask = (id, fields) =>
  request(`/api/works/tasks/${id}/`, { method: 'PATCH', body: fields })

export const deleteTask = (id) =>
  request(`/api/works/tasks/${id}/`, { method: 'DELETE' })

export const moveTask = (id, direction) =>
  request(`/api/works/tasks/${id}/move/`, { method: 'POST', body: { direction } })

export const fetchTaskImpact = (id) => request(`/api/works/tasks/${id}/impact/`)

/** Снять вердикты со всех отправок задачи — «перепроверить». */
export const recheckTask = (id) =>
  request(`/api/works/tasks/${id}/recheck/`, { method: 'POST' })

// --- ученик ---
//
// Единственный пока адрес его половины приложения: где учусь и где учился.
// Снятый курс из ответа не исчезает, у него стоит `active: false`.

//
// Все четыре читающих адреса ученика носят `?child=`, когда смотрит родитель.
// Подставляет его `viewedChild`, а не страницы: вопрос «чей экран» один, и
// ответ на него должен быть один — на сервере это `families.viewing`, здесь
// этот модуль. Ученику подставлять нечего, и сервер параметр от него не
// читает.
const withChild = (url) => {
  const child = childParam()
  if (!child) return url
  return url.includes('?') ? `${url}&${child}` : `${url}?${child}`
}

export const fetchStudentCourses = () => request(withChild('/api/student/courses/'))

/** Курс ученика целиком: учебный план с датами. Работы приходят отдельно. */
export const fetchStudentCourse = (id) =>
  request(withChild(`/api/student/courses/${id}/`))

/** Работы ученика: открытые и закрытые, с его продвижением по ним. */
export const fetchStudentWorks = () => request(withChild('/api/student/works/'))

/**
 * Журнал курса глазами семьи: строка одна — своя.
 *
 * `?child=` подставляется той же дверью, что и остальным ученическим
 * адресам: вопрос «чей это экран» один, и ответ на него должен быть один.
 */
export const fetchStudentJournal = (course, term = null) =>
  request(
    withChild(
      `/api/student/journal/?course=${course}${term === null ? '' : `&term=${term}`}`,
    ),
  )

export const fetchStudentWork = (id, version) =>
  request(
    withChild(
      `/api/student/works/${id}/${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    ),
  )

// --- родитель: дети, собеседники, разговоры ------------------------------------

export const fetchChildren = () => request('/api/family/children/')

export const fetchChildTeachers = () => request(withChild('/api/family/teachers/'))

/**
 * Переписка: список собеседников и один разговор.
 *
 * Разговор адресуется **человеком**, а не номером треда: так его и держат в
 * голове — «переписка с Ивановой», а не «тред 47». Семейная переписка ходила
 * своими адресами, пока казалась своим видом; собеседник природы разговора не
 * меняет, и адрес теперь один на всех.
 */
export const fetchTalks = () => request('/api/talks/')

export const fetchTalk = (person) => request(`/api/talks/${person}/`)

export const sendTalkMessage = (person, text, child = null) =>
  request(`/api/talks/${person}/`, {
    method: 'POST',
    // `child` — о ком разговор. Ставит его только родитель, и берётся он из
    // того же выбора, которым живёт весь его интерфейс (`viewedChild`)
    body: child ? { text, child } : { text },
  })

export const sendAnswer = (task, answer) =>
  request(`/api/student/tasks/${task}/answer/`, { method: 'POST', body: { answer } })

// --- фотографии работы ---------------------------------------------------------
//
// Кладёт их семья, размечает учитель, а смотрят обе стороны **одним и тем же**
// просмотрщиком — поэтому и адрес разметки один на двоих. Разведи его на две
// половины, и они разошлись бы: учитель обвёл бы одно, ученик увидел другое.

/**
 * Прислать снимок работы: по задаче или на всю работу разом.
 *
 * `child` едет телом, а не хвостом адреса: у multipart-запроса тела и так
 * достаточно, а хвост пришлось бы собирать вторым способом. Сервер читает
 * обоих (`families.viewing.subject_of`), и у ученика его нет вовсе.
 */
export const sendWorkPhoto = ({ work, task = null, file }) => {
  const form = new FormData()
  form.append('file', file)
  if (task) form.append('task', task)

  const child = viewedChild()
  if (child) form.append('child', child)

  return request(`/api/student/works/${work}/photos/`, { method: 'POST', body: form })
}

/** Забрать присланное — своё и пока окно открыто. */
export const removeWorkPhoto = (id) =>
  request(`/api/student/photos/${id}/`, { method: 'DELETE' })

/** Снимки одного ученика по работе: по работе целиком и по задачам. */
export const fetchWorkPhotos = (work, student) =>
  request(`/api/works/${work}/photos/?student=${student}`)

/** Что нарисовано поверх снимка: поворот, мазки и булавки. */
export const fetchPhotoMarkup = (id) => request(`/api/works/photos/${id}/`)

export const turnPhoto = (id, rotation) =>
  request(`/api/works/photos/${id}/`, { method: 'PATCH', body: { rotation } })

export const drawOnPhoto = (id, stroke) =>
  request(`/api/works/photos/${id}/strokes/`, { method: 'POST', body: stroke })

/**
 * Отмена: снимается **свой** последний мазок, а не чужой, и на той странице,
 * которую видно. Страница едет в адресе: у DELETE тела не бывает по-хорошему.
 */
export const undoOnPhoto = (id, page = 0) =>
  request(`/api/works/photos/${id}/strokes/?page=${page}`, { method: 'DELETE' })

export const pinPhotoNote = (id, { x, y, text, page = 0 }) =>
  request(`/api/works/photos/${id}/notes/`, {
    method: 'POST',
    body: { x, y, text, page },
  })

export const sayInPhotoNote = (note, text) =>
  request(`/api/works/notes/${note}/`, { method: 'POST', body: { text } })

export const removePhotoNote = (note) =>
  request(`/api/works/notes/${note}/`, { method: 'DELETE' })

/**
 * Подписанный адрес самой картинки.
 *
 * Той же дверью, что и скачивание вложения, — она отвечает обеим сторонам
 * («чьё это вложение», а не «кто вы по виду»), и заводить вторую значило бы
 * заводить второе место, где решается право на файл.
 */
export const photoUrl = (id) =>
  request(`/api/attachments/${id}/download/?json=1`).then((answer) => answer.url)

/** Очередь методиста: планы по его предметам, присланные на утверждение. */
export const fetchReviews = () => request('/api/plan/reviews/')

/*
 * Надзор адресуется **курсом**, а не запросом на утверждение.
 *
 * Запросом это было, и потому план был виден только присланный: очередь на
 * подпись служила и правом, и адресом. Право даёт назначение методистом,
 * поэтому адрес теперь — курс, а запрос стал состоянием плана.
 */
export const fetchReview = (courseId) => request(`/api/plan/reviews/${courseId}/`)

/**
 * Лента слотов чужого курса — вторая половина его раскладки.
 *
 * Та же лента, что у автора (`fetchPlanSlots`), и сшивается она тем же
 * `stitchLayout`: раскладка — правило, а не оформление, и «вид для
 * читателя», посчитанный отдельно, разошёлся бы с авторским молча.
 */
export const fetchReviewSlots = (courseId) =>
  request(`/api/plan/reviews/${courseId}/layout/slots/`)

export const approveReview = (courseId) =>
  request(`/api/plan/reviews/${courseId}/approve/`, { method: 'POST' })

export const returnReview = (courseId, comment) =>
  request(`/api/plan/reviews/${courseId}/return/`, {
    method: 'POST',
    body: { comment },
  })

/** Кто утверждает план курса — та же пара, что у назначения учителя. */
export const createMethodist = (course, user) =>
  request('/api/school/methodists/', { method: 'POST', body: { course, user } })

export const deleteMethodist = (id) =>
  request(`/api/school/methodists/${id}/`, { method: 'DELETE' })

// --- состав курса ---
//
// Снятие не удаляет строку, а ставит `removed_at`: ученик перестаёт работать
// в курсе, но продолжает видеть сделанное. Поэтому «вернуть» — это тот же
// POST той же пары, а не новая запись.

export const fetchStudents = (course) =>
  request(`/api/school/students/?course=${course}`)

export const enrolStudent = (course, student) =>
  request('/api/school/students/', { method: 'POST', body: { course, student } })

export const removeStudent = (id) =>
  request(`/api/school/students/${id}/`, { method: 'DELETE' })

/** Что сделает вставка списка — не делая ничего. */
export const previewRoster = (course, text) =>
  request(`/api/school/students/preview/?course=${course}`, {
    method: 'POST',
    body: { text },
  })

export const enrolRoster = (course, text) =>
  request(`/api/school/students/enrol/?course=${course}`, {
    method: 'POST',
    body: { text },
  })

/** Topics across every class for a period: slot_id → the plan lesson. */
export const fetchLayoutAgenda = (start, end) =>
  request(`/api/plan/layout/agenda/?${new URLSearchParams({ start, end })}`)

export const movePlanNodeTo = (id, parent, position) =>
  request(`/api/plan/${id}/move_to/`, {
    method: 'POST',
    body: { parent, position },
  })

export const movePlanNode = (id, direction) =>
  request(`/api/plan/${id}/move/`, { method: 'POST', body: { direction } })

export const movePlanSection = (id, direction) =>
  request(`/api/plan/sections/${id}/move/`, {
    method: 'POST',
    body: { direction },
  })

/*
 * Расписание школы — те же уроки, только все.
 *
 * Отдельной таблицы у него нет: `?scope=school` снимает умолчание «только
 * свои», и получается расписание школы. Пишет ведущий курса или
 * администратор — это решает сервер, здесь просто адрес.
 */
export const fetchSchoolSlots = (params) =>
  request(`/api/slots/?${new URLSearchParams({ ...params, scope: 'school' })}`)

export const fetchScheduleSummary = (params) =>
  request(`/api/slots/summary/?${new URLSearchParams(params)}`)

// --- schedule lessons ---

export const fetchSlotStats = (classId) =>
  request(`/api/slots/stats/?course=${encodeURIComponent(classId)}`)

export const fetchAgenda = (start, end) =>
  request(`/api/slots/agenda/?${new URLSearchParams({ start, end })}`)

export const createSlot = (fields) =>
  request('/api/slots/', { method: 'POST', body: fields })

export const updateSlot = (id, fields) =>
  request(`/api/slots/${id}/`, { method: 'PATCH', body: fields })

export const deleteSlot = (id) =>
  request(`/api/slots/${id}/`, { method: 'DELETE' })

// перенос — не правка даты, а отмена плюс дополнительное занятие: след
// срыва и его компенсации нужен календарной оси, и делает это сервер одной
// транзакцией
export const moveSlot = (id, fields) =>
  request(`/api/slots/${id}/move/`, { method: 'POST', body: fields })

// одно занятие целиком — то, с чем работают на его странице: тема из
// плана, работы и соседи по курсу
export const fetchSlotCard = (id) => request(`/api/slots/${id}/card/`)

// журнал занятия: список строится по составу курса, а отметки — только у
// тех, кого отметили
export const fetchAttendance = (slot) => request(`/api/slots/${slot}/attendance/`)

export const markAttendance = (slot, marks) =>
  request(`/api/slots/${slot}/attendance/`, { method: 'POST', body: { marks } })

// долги по записи: прошедшие занятия, за которыми ничего не сказано
export const fetchUnclosed = () => request('/api/slots/unclosed/')

export const closeSlots = (closed) =>
  request('/api/slots/close/', { method: 'POST', body: { closed } })

/*
 * Ряд уроков: один час, повторённый через неделю или через две.
 *
 * Считает его сервер целиком — сколько дат попадёт под каникулы и сколько
 * мест занято, знает только он. Ответ той же формы, что у копирования
 * периода: создано, пропущено, чем помешали.
 */
export const repeatSlot = (fields) =>
  request('/api/slots/repeat/', { method: 'POST', body: fields })

export const copySlots = (payload) =>
  request('/api/slots/copy/', { method: 'POST', body: payload })

/*
 * Массовое удаление: период курса, при желании суженный до ряда.
 *
 * Ряд — это день недели и номер: «все вторники, третий час, до конца
 * года». Отдельного эндпоинта под него нет намеренно — путь удаления один,
 * и два счёта того, что уходит, разошлись бы молча.
 */
export const deleteSlots = ({ classId, start, end, onlyRegular, weekday, number }) => {
  // параметры уезжают строкой запроса: у DELETE тела нет
  const query = new URLSearchParams({
    course: classId,
    start,
    end,
    only_regular: onlyRegular,
  })
  if (weekday !== undefined) query.set('weekday', weekday)
  if (number !== undefined) query.set('lesson_number', number)

  return request(`/api/slots/bulk/?${query}`, { method: 'DELETE' })
}


// --- дев-дверь: вход кем угодно без Google ---
//
// Живёт за флагом `E2E_TEST_LOGIN`, и при выключенном флаге маршрутов нет
// вовсе — поэтому «есть ли дверь» проверяется запросом, а не переменной
// сборки: в проде он честно отвечает 404, и переключателя не будет.

export const fetchTestPeople = (as) => request('/api/test/people/', { as })

export const loginAsTestUser = (email, as) =>
  request('/api/test/login/', { method: 'POST', body: { email }, as })

/**
 * Поиск задач: слова и грани идут одним запросом, потому что сужают один и тот
 * же набор. Грани повторяются в строке запроса (`tag=1&tag=2`) — это «и», а не
 * список.
 */
export const searchProblems = (query) => {
  const params = new URLSearchParams()
  if (query.text) params.set('text', query.text)
  if (query.level) params.set('level', query.level)
  if (query.shelved) params.set('shelved', query.shelved)
  if (query.subject) params.set('subject', query.subject)
  ;(query.tags || []).forEach((id) => params.append('tag', id))
  ;(query.uses || []).forEach((id) => params.append('uses', id))
  ;(query.avoids || []).forEach((id) => params.append('avoids', id))
  return request(`/api/bank/search/?${params}`)
}

/** Поиск выражением: дерево уходит телом, ответ той же формы, что у граней. */
export const searchByExpression = (expression) =>
  request('/api/bank/search/', { method: 'POST', body: { expression } })

/**
 * Темы: они же сохранённые поиски. Одна вещь — названное условие с местом в
 * дереве, — поэтому и адрес у них один.
 */
export const saveTopic = (fields) =>
  request('/api/bank/topics/', { method: 'POST', body: fields })

export const updateTopic = (id, fields) =>
  request(`/api/bank/topics/${id}/`, { method: 'PATCH', body: fields })

export const deleteTopic = (id) =>
  request(`/api/bank/topics/${id}/`, { method: 'DELETE' })

/**
 * Взять задачу или раздел к себе. `mode` — «ссылка» или «своя копия», и это
 * разные вещи: ссылка оставляет одну задачу на всех, копия заводит свою.
 */
export const copyIntoSource = (body) =>
  request('/api/bank/copy/', { method: 'POST', body })

export const declareAnalogue = (problem, other) =>
  request('/api/bank/analogues/', { method: 'POST', body: { problem, other } })

export const leaveFamily = (problem) =>
  request('/api/bank/analogues/', { method: 'DELETE', body: { problem } })

/** Хронология курса: где какое понятие вводится. */
export const fetchChronology = (course) =>
  request(`/api/bank/chronology/${course}/`)

export const introduceTag = (course, node, tag) =>
  request(`/api/bank/chronology/${course}/`, { method: 'POST', body: { node, tag } })

export const forgetTag = (course, tag) =>
  request(`/api/bank/chronology/${course}/`, { method: 'DELETE', body: { tag } })

export const fetchTopics = () => request('/api/bank/topics/')

/**
 * Что лежит в теме. Курс и урок необязательны: без них тема отвечает «что
 * вообще есть», с ними — «что из этого мы умеем к этому дню».
 */
export const fetchTopic = (id, { course, upto } = {}) => {
  const params = new URLSearchParams()
  if (course) params.set('course', course)
  if (upto) params.set('upto', upto)
  const query = params.toString()
  return request(`/api/bank/topics/${id}/${query ? `?${query}` : ''}`)
}

/**
 * Собрать работу из набора задач банка. Порядок в списке — это решение
 * учителя, поэтому уезжает он как есть, а не множеством.
 */
export const assembleWork = (body) =>
  request('/api/works/from-bank/', { method: 'POST', body })

export const addFromBank = (work, problems) =>
  request(`/api/works/${work}/add-from-bank/`, { method: 'POST', body: { problems } })

/** Часы курса за период — ими называют занятие, на котором задали работу. */
/**
 * Часы курса. Границы необязательны: без них сервер отдаёт год целиком.
 *
 * Пустое имя в запрос не попадает вовсе — `URLSearchParams` пишет `undefined`
 * строкой, и `start=undefined` сервер разберёт как «дату не поняли», то есть
 * вернёт не тот список, о котором просили.
 */
export const fetchCourseSlots = (course, { start, end } = {}) => {
  const query = new URLSearchParams({ course })
  if (start) query.set('start', start)
  if (end) query.set('end', end)

  return request(`/api/slots/?${query}`)
}

/**
 * Накатить условие из банка на **эту** ячейку — или снять его (`null`).
 * Не то же, что дописать задачи в конец работы: тут названо место.
 */
export const takeIntoCell = (task, problem) =>
  request(`/api/works/tasks/${task}/take/`, { method: 'POST', body: { problem } })

/**
 * След ученика: что он решал за всё время, собранный по условиям.
 * Учителю — по своим курсам, ученику — свой целиком.
 */
export const fetchTrack = (student) => request(`/api/works/track/${student}/`)

/**
 * Массовый импорт задач в книгу: матрица ячеек или файл (CSV, xlsx).
 * `preview` ничего не пишет и ни от чего не отказывается — ошибки приезжают
 * списком в теле.
 */
export const importIntoSource = (source, body) =>
  request(`/api/bank/sources/${source}/import/`, { method: 'POST', body })

export const importFileIntoSource = (source, file) => {
  const form = new FormData()
  form.append('file', file)
  return request(`/api/bank/sources/${source}/import/`, { method: 'POST', body: form })
}

/**
 * Предложения: сообщить об опечатке, предложить тег, задачу или разбор.
 * Кому это идёт, решает сервер по владению того, о чём речь.
 */
export const fetchProposals = () => request('/api/bank/proposals/')

export const propose = (body) =>
  request('/api/bank/proposals/', { method: 'POST', body })

export const sayOnProposal = (id, text) =>
  request(`/api/bank/proposals/${id}/`, { method: 'POST', body: { text } })

export const resolveProposal = (id, body) =>
  request(`/api/bank/proposals/${id}/`, { method: 'PATCH', body })

/*
 * Сообщения разработчику: «сломалось» и «хорошо бы».
 *
 * Пишут оба вида пользователей, читает суперпользователь — это единственная
 * пара адресов в приложении с такой формой, и живёт она вне `/api/school/`
 * намеренно: разговор с разработчиком идёт через школы, а не внутри одной.
 */
export const sendFeedback = (body) =>
  request('/api/feedback/', { method: 'POST', body })

export const fetchFeedback = (params = {}) =>
  request(`/api/feedback/?${new URLSearchParams(params)}`)

export const fetchFeedbackSummary = () => request('/api/feedback/summary/')

export const markFeedbackHandled = (id) =>
  request(`/api/feedback/${id}/handled/`, { method: 'POST' })

// --- расписание звонков ---------------------------------------------------------
//
// Читают все в школе, правит администратор; список приходит и уходит целиком —
// номер урока и есть ключ, и построчная правка потребовала бы разговора про
// удаление там, где удаляют ровно при сокращении дня.

export const fetchBells = () => request('/api/school/bells/')

export const saveBells = (bells) =>
  request('/api/school/bells/', { method: 'PUT', body: { bells } })
