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
  if (body) headers['Content-Type'] = 'application/json'

  const token = getToken()
  if (auth && token) headers['Authorization'] = `Token ${token}`

  // /api проксируется Vite на backend:8000, поэтому путь относительный
  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    const detail = data?.detail || data?.non_field_errors?.[0] || 'Запрос не удался'
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

export const logout = () => request('/api/auth/logout/', { method: 'POST' })
