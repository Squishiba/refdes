// The only place the browser talks to Python. Every request carries the launch
// token (reads too); the server rejects a request without it before routing.
const token = document.querySelector('meta[name="refdes-token"]').content;

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'X-Refdes-Token': token };
  const init = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let payload = null;
  try { payload = await res.json(); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) {
    const err = new Error((payload && payload.error) || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}
