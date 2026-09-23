const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  'https://smart-agri-survillance-api.onrender.com'

export const WS_URL =
  import.meta.env.VITE_WS_URL ||
  'wss://smart-agri-survillance-api.onrender.com/ws'

export function getToken() {
  return localStorage.getItem('access_token')
}

export function setToken(token) {
  if (token) localStorage.setItem('access_token', token)
  else localStorage.removeItem('access_token')
}

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request(path, options = {}) {
  const token = getToken()
  const headers = {
    ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  }

  let res
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  } catch (err) {
    throw new ApiError(
      'Could not reach the backend. Is it running at ' + API_BASE_URL + '?',
      0,
      null,
    )
  }

  if (res.status === 401) {
    setToken(null)
    if (!path.includes('/auth/login')) {
      window.location.href = '/login'
    }
  }

  if (!res.ok) {
    let detail = null
    try {
      const body = await res.json()
      detail = body.detail
    } catch (_) {
      /* ignore */
    }
    // FastAPI's own automatic Pydantic validation errors (e.g. a Field
    // min_length violation) come back as an array of error objects
    // rather than the plain string our own HTTPException(detail=...)
    // calls use - normalize both shapes to a readable string here so
    // every caller can just show `err.detail` safely.
    if (Array.isArray(detail)) {
      detail = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status, detail)
  }

  if (res.status === 204) return null
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return res.json()
  return res.text()
}

export const api = {
  get: (path) => request(path, { method: 'GET' }),
  post: (path, body) => request(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path) => request(path, { method: 'DELETE' }),
  upload: (path, formData) => request(path, { method: 'POST', body: formData }),
}

export function mediaUrl(relativeStoragePath) {
  if (!relativeStoragePath) return null
  return `${API_BASE_URL}/storage/${relativeStoragePath}`
}

export function streamUrl(cameraId) {
  return `${API_BASE_URL}/api/cameras/${cameraId}/stream`
}

export { API_BASE_URL, ApiError }
