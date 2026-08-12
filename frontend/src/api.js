const TOKEN_KEY = 'authToken'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {}
  // у FormData свой Content-Type с границей блоков — его ставит браузер
  const isForm = body instanceof FormData
  if (body && !isForm) headers['Content-Type'] = 'application/json'

  const token = getToken()
  if (auth && token) headers['Authorization'] = `Token ${token}`

  // /api проксируется Vite на backend:8000, поэтому путь относительный
  const response = await fetch(path, {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    // DRF отдаёт либо detail, либо ошибки по полям — берём первое понятное
    const fieldError =
      data && typeof data === 'object' ? Object.values(data).flat()[0] : null
    const detail = data?.detail || fieldError || 'Запрос не удался'
    throw new ApiError(detail, response.status)
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

// --- учебные годы и календарь ---

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

// --- классы ---

// без года — все классы владельца, они нужны сводному расписанию
export const fetchClasses = (yearId) =>
  request(
    yearId ? `/api/classes/?year=${encodeURIComponent(yearId)}` : '/api/classes/',
  )

export const createClass = (fields) =>
  request('/api/classes/', { method: 'POST', body: fields })

export const renameClass = (id, name) =>
  request(`/api/classes/${id}/`, { method: 'PATCH', body: { name } })

export const deleteClass = (id) =>
  request(`/api/classes/${id}/`, { method: 'DELETE' })

// --- учебный план ---

export const fetchPlan = (classId) =>
  request(`/api/plan/?class=${encodeURIComponent(classId)}`)

export const createPlanNode = (fields) =>
  request('/api/plan/', { method: 'POST', body: fields })

export const updatePlanNode = (id, fields) =>
  request(`/api/plan/${id}/`, { method: 'PATCH', body: fields })

export const deletePlanNode = (id, keepChildren) =>
  request(`/api/plan/${id}/?keep_children=${keepChildren ? 'true' : 'false'}`, {
    method: 'DELETE',
  })

export const importPlanCsv = (classId, file, mode) => {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)

  return request(`/api/plan/import/?class=${encodeURIComponent(classId)}`, {
    method: 'POST',
    body: form,
  })
}

/**
 * Скачивание плана.
 *
 * Простая ссылка не подойдёт: эндпоинт требует токен в заголовке, поэтому
 * тянем файл запросом и отдаём браузеру как blob.
 */
export const downloadPlanCsv = async (classId) => {
  const token = getToken()
  const response = await fetch(
    `/api/plan/export/?class=${encodeURIComponent(classId)}`,
    { headers: token ? { Authorization: `Token ${token}` } : {} },
  )

  if (!response.ok) {
    throw new ApiError('Не удалось выгрузить план', response.status)
  }

  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const name = encoded ? decodeURIComponent(encoded[1]) : 'plan.csv'

  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export const fetchLayout = (classId, period = {}) =>
  request(`/api/plan/layout/?${new URLSearchParams({ class: classId, ...period })}`)

/** Темы уроков по всем классам за период: slot_id → урок плана. */
export const fetchLayoutAgenda = (start, end) =>
  request(`/api/plan/layout/agenda/?${new URLSearchParams({ start, end })}`)

export const fetchLayoutSummary = (classId) =>
  request(`/api/plan/layout/summary/?class=${encodeURIComponent(classId)}`)

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

// --- уроки расписания ---

export const fetchSlots = (classId) =>
  request(`/api/slots/?class=${encodeURIComponent(classId)}`)

export const fetchSlotStats = (classId) =>
  request(`/api/slots/stats/?class=${encodeURIComponent(classId)}`)

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
  // параметры массового удаления идут в строке запроса, тела у DELETE нет
  const query = new URLSearchParams({
    class: classId,
    start,
    end,
    only_regular: onlyRegular,
  })
  return request(`/api/slots/bulk/?${query}`, { method: 'DELETE' })
}
