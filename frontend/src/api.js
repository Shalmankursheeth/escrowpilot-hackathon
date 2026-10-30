const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
let token = null;
try { token = localStorage.getItem("ep_token"); } catch {}

export const setToken = (t) => {
  token = t;
  try { t ? localStorage.setItem("ep_token", t) : localStorage.removeItem("ep_token"); } catch {}
};
export const hasToken = () => !!token;

export async function api(path, method = "GET", body) {
  const res = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    const d = data && data.detail;
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join("; ") : d || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const money = (cents, cur = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: cur }).format(cents / 100);
