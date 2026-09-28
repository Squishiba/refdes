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

// The raw-bytes POST for the one endpoint that takes them: `POST /api/assets`
// (docs/design/editor-image-upload.md §11 -- the bytes are the body, metadata
// lives in the query string, and the content type is exactly
// `application/octet-stream`). It lives here rather than as a bare fetch in a
// caller so the launch token stays api.js's alone, and it mirrors `api`'s
// error shape -- `status` and the server's `payload` on the thrown Error --
// because the caller branches on both (409 conflict vs. refusal, §8 and §10).
export async function postRaw(path, bytes) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'X-Refdes-Token': token, 'Content-Type': 'application/octet-stream' },
    body: bytes,
  });
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
