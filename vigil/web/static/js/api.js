// The dashboard's API: every call carries the scene (live, or a replay at its clock).

export class ApiError extends Error {}

export function sceneParams(state) {
  return state.mode === "replay" ? { replay: state.episode, at: state.clock } : {};
}

export async function get(path, params = {}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined));
  const response = await fetch(`${path}${query.size ? `?${query}` : ""}`, { signal });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(`${response.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return response.json();
}

export function imageUrl(frameId, scene, { overlay = true, width = 1280 } = {}) {
  // scene: the clock the API answered with, so the image shows what the rest of the page shows
  const params = new URLSearchParams({ overlay, width });
  if (scene.replay) params.set("replay", scene.replay);
  params.set("at", scene.clock);
  return `/api/frames/${frameId}/image?${params}`;
}
