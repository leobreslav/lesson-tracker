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

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {}
  // FormData has its own Content-Type with a boundary; the browser sets it
  const isForm = body instanceof FormData
  if (body && !isForm) headers['Content-Type'] = 'application/json'

  const token = getToken()
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

/** Take a template into a course plan — a copy, not a link. */
export const importTemplate = (payload) =>
  request('/api/plan/import-from-template/', { method: 'POST', body: payload })

export const fetchSubjects = () => request('/api/school/subjects/')

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
 */
export const downloadPlan = async (classId, format = 'xlsx') => {
  const token = getToken()
  const query = new URLSearchParams({ course: classId })
  const path = format === 'xlsx' ? 'export-xlsx' : 'export'
  const response = await fetch(`/api/plan/${path}/?${query}`, {
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

export const uploadAttachment = ({ planRow, templateRow, studentWork, file, title }) => {
  const form = new FormData()
  if (planRow) form.append('plan_row', planRow)
  if (templateRow) form.append('template_row', templateRow)
  if (studentWork) form.append('student_work', studentWork)
  form.append('file', file)
  if (title) form.append('title', title)

  return request('/api/attachments/', { method: 'POST', body: form })
}

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
export const setVerdict = (id, isCorrect) =>
  request(`/api/works/submissions/${id}/`, {
    method: 'PATCH',
    body: { is_correct: isCorrect },
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

export const fetchStudentCourses = () => request('/api/student/courses/')

/** Курс ученика целиком: учебный план с датами. Работы приходят отдельно. */
export const fetchStudentCourse = (id) => request(`/api/student/courses/${id}/`)

/** Работы ученика: открытые и закрытые, с его продвижением по ним. */
export const fetchStudentWorks = () => request('/api/student/works/')

export const fetchStudentWork = (id, version) =>
  request(
    `/api/student/works/${id}/${version ? `?version=${encodeURIComponent(version)}` : ''}`,
  )

export const sendAnswer = (task, answer) =>
  request(`/api/student/tasks/${task}/answer/`, { method: 'POST', body: { answer } })

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

export const clearSlots = ({ classId, start, end, onlyRegular }) => {
  // bulk delete takes its parameters in the query string; DELETE has no body
  const query = new URLSearchParams({
    course: classId,
    start,
    end,
    only_regular: onlyRegular,
  })
  return request(`/api/slots/bulk/?${query}`, { method: 'DELETE' })
}


// --- дев-дверь: вход кем угодно без Google ---
//
// Живёт за флагом `E2E_TEST_LOGIN`, и при выключенном флаге маршрутов нет
// вовсе — поэтому «есть ли дверь» проверяется запросом, а не переменной
// сборки: в проде он честно отвечает 404, и переключателя не будет.

export const fetchTestPeople = () => request('/api/test/people/')

export const loginAsTestUser = (email) =>
  request('/api/test/login/', { method: 'POST', body: { email } })
