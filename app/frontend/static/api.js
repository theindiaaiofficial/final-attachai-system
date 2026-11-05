let csrfToken = null;

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, timeout = 30000, download = false } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const headers = { Accept: "application/json" };
  if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (body && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  try {
    const response = await fetch(path, { method, headers, credentials: "same-origin", signal: controller.signal, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined, cache: "no-store" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      const detail = Array.isArray(result.detail) ? result.detail.map(x => `${x.loc?.slice(1).join(".") || "Input"}: ${x.msg}`).join("; ") : result.detail;
      if (response.status === 401 && path !== "/admin/auth/login") window.dispatchEvent(new Event("auth-expired"));
      throw new ApiError(detail || `Request failed (${response.status})`, response.status);
    }
    return download ? await response.blob() : response.status === 204 ? null : await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("Request timed out. Refresh to check the current state before retrying.", 408);
    if (error instanceof ApiError) throw error;
    throw new ApiError("Could not connect to the server. Check your connection and retry.", 0);
  } finally { clearTimeout(timer); }
}

export async function authenticate() {
  const session = await api("/admin/auth/session");
  csrfToken = session.csrf_token;
  return session;
}

export async function logout() {
  await api("/admin/auth/logout", { method: "POST" });
  csrfToken = null;
  location.assign("/admin/login");
}

export function saveFile(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
