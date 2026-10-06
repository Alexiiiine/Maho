export async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not load the workspace.');
  return data;
}
export const runURL = id => `/api/runs/${encodeURIComponent(id)}`;
export const fileURL = (id, name, download = false, revision = '') => `${runURL(id)}/files/${name}?${new URLSearchParams({ ...(download ? { download: '1' } : {}), ...(revision ? { v: revision } : {}) })}`;
export const thumbnailURL = (id, name, revision = '') => `${runURL(id)}/thumbnails/${name}${revision ? `?v=${encodeURIComponent(revision)}` : ''}`;
export function duration(value) {
  if (!value) return '—';
  const seconds = Math.round(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
export const secondsLabel = clip => `${(clip.rendered_duration_seconds ?? clip.estimated_finished_duration_seconds).toFixed(1)}s`;
