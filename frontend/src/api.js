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

  // Vite proxies /api to backend:8000, so the path stays relative
  const response = await fetch(path, {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })

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

/** Removes ALL of the user's data, not only the example. */
export const wipeAllData = () =>
  request('/api/onboarding/demo/', { method: 'DELETE' })

// --- school years and the calendar ---

export const fetchSchoolYears = () => request('/api/calendar/years/')

export const fetchSchoolYear = (id) => request(`/api/calendar/years/${id}/`)

export const createSchoolYear = (fields) =>
  request('/api/calendar/years/', { method: 'POST', body: fields })

export const deleteSchoolYear = (id) =>
  request(`/api/calendar/years/${id}/`, { method: 'DELETE' })

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

export const fetchSchool = () => request('/api/school/')

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

export const fetchMembers = () => request('/api/school/members/')

export const setMemberRole = (id, isAdmin) =>
  request(`/api/school/members/${id}/`, {
    method: 'PATCH',
    body: { is_school_admin: isAdmin },
  })

export const fetchInvitations = () => request('/api/school/invitations/')

export const createInvitation = (fields) =>
  request('/api/school/invitations/', { method: 'POST', body: fields })

export const deleteInvitation = (id) =>
  request(`/api/school/invitations/${id}/`, { method: 'DELETE' })

/**
 * Detach a teacher from the school. Their lessons and plans are kept.
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

export const updatePlanNode = (id, fields) =>
  request(`/api/plan/${id}/`, { method: 'PATCH', body: fields })

export const deletePlanNode = (id, keepChildren) =>
  request(`/api/plan/${id}/?keep_children=${keepChildren ? 'true' : 'false'}`, {
    method: 'DELETE',
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

export const fetchAttachments = (params) =>
  request(`/api/attachments/?${new URLSearchParams(params)}`)

export const uploadAttachment = ({ planRow, templateRow, file, title }) => {
  const form = new FormData()
  if (planRow) form.append('plan_row', planRow)
  if (templateRow) form.append('template_row', templateRow)
  form.append('file', file)
  if (title) form.append('title', title)

  return request('/api/attachments/', { method: 'POST', body: form })
}

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
export const fetchProgress = () => request('/api/plan/progress/')

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

/** Очередь методиста: планы по его предметам, присланные на утверждение. */
export const fetchReviews = () => request('/api/plan/reviews/')

export const fetchReview = (id) => request(`/api/plan/reviews/${id}/`)

export const approveReview = (id) =>
  request(`/api/plan/reviews/${id}/approve/`, { method: 'POST' })

export const returnReview = (id, comment) =>
  request(`/api/plan/reviews/${id}/return/`, {
    method: 'POST',
    body: { comment },
  })

/** Кто утверждает план курса — та же пара, что у назначения учителя. */
export const createMethodist = (course, user) =>
  request('/api/school/methodists/', { method: 'POST', body: { course, user } })

export const deleteMethodist = (id) =>
  request(`/api/school/methodists/${id}/`, { method: 'DELETE' })

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

// --- the school-wide timetable: read by all, written by admins ---

export const fetchMasterSlots = (params) =>
  request(`/api/school/master-slots/?${new URLSearchParams(params)}`)

export const fetchMasterSummary = (params) =>
  request(`/api/school/master-slots/summary/?${new URLSearchParams(params)}`)

export const createMasterSlot = (fields) =>
  request('/api/school/master-slots/', { method: 'POST', body: fields })

export const deleteMasterSlot = (id) =>
  request(`/api/school/master-slots/${id}/`, { method: 'DELETE' })

export const copyMasterSlots = (payload) =>
  request('/api/school/master-slots/copy/', { method: 'POST', body: payload })

export const clearMasterSlots = ({ start, end, courseId }) =>
  request(
    `/api/school/master-slots/bulk/?${new URLSearchParams({
      start,
      end,
      ...(courseId ? { course: courseId } : {}),
    })}`,
    { method: 'DELETE' },
  )

/** What the school timetable would bring me — nothing is written. */
export const fetchImportPreview = (params) =>
  request(`/api/schedule/import-preview/?${new URLSearchParams(params)}`)

/** Copy my rows of the timetable into my own schedule. Once, not a sync. */
export const importFromSchool = (payload) =>
  request('/api/schedule/import-from-school/', { method: 'POST', body: payload })

// --- schedule lessons ---

export const fetchSlots = (classId) =>
  request(`/api/slots/?course=${encodeURIComponent(classId)}`)

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
