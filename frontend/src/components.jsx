import React, { useEffect, useRef, useState } from 'react';
import { request, duration, fileURL, thumbnailURL, secondsLabel } from './api.js';

export function Icon({ name, size = 18 }) {
  const paths = {
    film: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
    document: <><path d="M14 3H5v18h14V8ZM14 3v5h5M8 12h8M8 16h8" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.5 6.5A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.5 5.5" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function History({ runs, selected, onSelect, onRefresh }) {
  const [query, setQuery] = useState('');
  const filtered = runs.filter(run => `${run.filename} ${run.id}`.toLowerCase().includes(query.toLowerCase()));
  return <aside className="history">
    <div className="history-heading"><h2>Previous runs</h2><button className="icon-button" aria-label="Refresh runs" onClick={onRefresh}><Icon name="refresh" /></button></div>
    <div className="search"><Icon name="search" /><input aria-label="Search runs" placeholder="Search runs" value={query} onChange={e => setQuery(e.target.value)} /></div>
    <nav aria-label="Run history" className="run-list">{filtered.map(run => <button key={run.id} className={`run-row ${selected === run.id ? 'selected' : ''}`} aria-current={selected === run.id ? 'page' : undefined} onClick={() => onSelect(run.id)}>
      <Icon name="film" size={20} /><span><strong>{run.filename}</strong><small>{run.clip_count} clips · {duration(run.duration_seconds)}{run.status !== 'completed' ? ` · ${run.status}` : ''}</small><time>{run.created_at ? new Date(run.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : ''}</time></span>
    </button>)}</nav>
    {!filtered.length ? <p className="empty-note">{runs.length ? 'No matching runs.' : 'Your runs will appear here.'}</p> : null}
    <p className="local-note">Saved on this computer</p>
  </aside>;
}

export function Video({ id, name, label, available = true, revision = '' }) {
  const [error, setError] = useState(false);
  if (!available) return <div className="video-empty">{name === 'source' ? 'The original video is no longer at its saved path.' : 'This clip has not been rendered yet.'}</div>;
  return <div className="video-frame"><video key={`${id}-${name}-${revision}`} controls preload="metadata" aria-label={label} poster={thumbnailURL(id, name, revision)} src={fileURL(id, name === 'source' ? 'source' : `${name}.mp4`, false, revision)} onError={() => setError(true)} />{error ? <p className="error">This browser could not play the file. You can download it below.</p> : null}</div>;
}

export function Overview({ run, onSelection }) {
  const [selected, setSelected] = useState(run.clips[0]?.clip_id);
  const clip = run.clips.find(c => c.clip_id === selected) || run.clips[0];
  const settings = run.settings;
  return <div className="overview">
    <section className="media-panel input-panel"><h2>Input video</h2>
      <Video key={`${run.id}-source`} id={run.id} name="source" label="Input video" available={run.source_available} />
      <dl className="file-details"><dt>Filename</dt><dd>{run.filename}</dd><dt>Duration</dt><dd>{duration(run.duration_seconds)}</dd><dt>Path</dt><dd className="path">{run.source_video}</dd></dl>
      <div className="run-settings"><h3>Run settings</h3><p>{settings.count ?? 5} clips maximum · {settings.min_seconds ?? 30}–{settings.max_seconds ?? 60} seconds</p><p className="muted">{settings.model || 'Model not recorded'}{settings.reasoning_effort ? ` · ${settings.reasoning_effort} reasoning` : ''} · Your editorial prompt</p>
        <p className="muted">Padding: {run.render_settings?.lead_seconds ?? 0}s before · {run.render_settings?.tail_seconds ?? 0}s after speech</p>
        <details><summary>View input settings</summary><dl><dt>Output folder</dt><dd className="path">{run.output_directory}</dd><dt>Editorial instructions</dt><dd>{settings.criteria || 'Default editorial prompt'}</dd></dl>{settings.project_info && Object.keys(settings.project_info).length ? <pre>{JSON.stringify(settings.project_info, null, 2)}</pre> : null}{settings.assignment_notes ? <p>{settings.assignment_notes}</p> : null}{settings.editorial_prompt ? <details><summary>Selection prompt</summary><pre>{settings.editorial_prompt}</pre></details> : null}</details>
      </div>
    </section>
    <section className="media-panel output-panel"><h2>Output clips</h2>
      {clip ? <><Video key={`${run.id}-${clip.clip_id}-${clip.render_revision}`} id={run.id} name={clip.clip_id} revision={clip.render_revision} label="Selected output clip" available={clip.available} />
        <div className="clip-title"><h3>{clip.clip_id.replace('clip_', '')} {clip.title}</h3><span>{secondsLabel(clip)}</span></div>
        <p className="quote">“{clip.hook}”</p>
        <div className="download-links">{clip.available ? <><a href={fileURL(run.id, `${clip.clip_id}.mp4`, true)} download><Icon name="download" />Download MP4</a><a href={fileURL(run.id, `${clip.clip_id}.srt`, true)} download><Icon name="document" />Subtitles</a></> : null}<button onClick={onSelection}><Icon name="document" />View selection</button></div>
        <nav aria-label="Output clips" className="clip-list">{run.clips.map(c => <button key={c.clip_id} className={`clip-row ${c.clip_id === clip.clip_id ? 'selected' : ''}`} aria-pressed={c.clip_id === clip.clip_id} onClick={() => setSelected(c.clip_id)}>
          {c.available ? <img src={thumbnailURL(run.id, c.clip_id, c.render_revision)} alt="" loading="lazy" /> : <span className="thumbnail-empty"><Icon name="film" /></span>}<strong>{c.clip_id.replace('clip_', '')} {c.title}</strong><span>{secondsLabel(c)}</span>
        </button>)}</nav>
        <details className="editor-notes"><summary>Clip details</summary><p>{clip.editorial_reason}</p><p className="muted">Source: {clip.source_start} → {clip.source_end}</p><p>{clip.transcript_excerpt}</p>{clip.internal_cuts.length ? <p>{clip.internal_cuts.length} internal cut{clip.internal_cuts.length === 1 ? '' : 's'} applied.</p> : null}</details>
      </> : <div className="empty-output"><Icon name="film" size={32} /><h3>{run.status === 'running' ? 'Your clips are on the way' : 'No clips saved yet'}</h3><p>Transcript analysis and rendered clips will appear here.</p></div>}
    </section>
  </div>;
}

export function Transcript({ run }) {
  const [query, setQuery] = useState('');
  const lines = query ? run.transcript.split('\n').filter(line => line.toLowerCase().includes(query.toLowerCase())).join('\n') : run.transcript;
  return <section className="text-view"><div className="text-toolbar"><h2>Timestamped transcript</h2><a href={fileURL(run.id, 'transcript', true)} download>Download TXT</a><a href={fileURL(run.id, 'words', true)} download>Word timestamps</a></div>
    <div className="search transcript-search"><Icon name="search" /><input aria-label="Search transcript" placeholder="Search transcript" value={query} onChange={e => setQuery(e.target.value)} /></div><pre className="transcript">{run.transcript ? lines || 'No matching transcript lines.' : 'The transcript will appear after transcription completes.'}</pre>
  </section>;
}

export function NewRun({ token, defaults, onClose, onCreated }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { const dialog = ref.current; dialog.showModal(); dialog.querySelector('input').focus(); return () => dialog.close(); }, []);
  async function submit(event) {
    event.preventDefault(); setError(''); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      const result = await request('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Maho-Token': token }, body: JSON.stringify({ video: data.get('video'), count: Number(data.get('count')), min_seconds: Number(data.get('min')), max_seconds: Number(data.get('max')), lead_seconds: Number(data.get('lead')), tail_seconds: Number(data.get('tail')), criteria: data.get('criteria') }) });
      onCreated(result.id);
    } catch (e) { setError(e.message); setBusy(false); }
  }
  return <dialog ref={ref} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }} aria-labelledby="new-run-title"><form onSubmit={submit}>
    <div className="dialog-heading"><h2 id="new-run-title">New run</h2><button className="icon-button" type="button" onClick={onClose} disabled={busy} aria-label="Close new run"><Icon name="close" /></button></div>
    <p className="muted">Choose a video on this computer. Maho will transcribe it, pick clips with your prompt, and save the exports.</p>
    <p className="muted">{defaults ? `${defaults.model} · ${defaults.reasoning_effort} reasoning` : 'Loading model settings…'}</p>
    <label>Video file path<input name="video" placeholder="C:\Videos\interview.mp4" required autoFocus /></label>
    <div className="form-row"><label>Maximum clips<input name="count" type="number" defaultValue={defaults?.count ?? 5} min="1" max="50" required /></label><label>Minimum seconds<input name="min" type="number" defaultValue={defaults?.min_seconds ?? 30} min="1" max="3600" required /></label><label>Maximum seconds<input name="max" type="number" defaultValue={defaults?.max_seconds ?? 60} min="1" max="3600" required /></label></div>
    <div className="form-row padding-fields"><label>Seconds before first word<input name="lead" type="number" defaultValue={defaults?.lead_seconds ?? 1.5} min="0" max="10" step="0.1" required /></label><label>Seconds after last word<input name="tail" type="number" defaultValue={defaults?.tail_seconds ?? 1.5} min="0" max="10" step="0.1" required /></label></div>
    <p className="muted">Padding adds time to the selected clip length. If nearby speech leaves too little room, Maho holds the frame with silence.</p>
    <label>Editorial instructions<textarea name="criteria" rows="3" defaultValue="Exclude false starts and production chatter. Start and end on complete thoughts." /></label>
    {error ? <p className="error" role="alert">{error}</p> : null}
    <div className="dialog-actions"><button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button><button className="primary" disabled={busy || !token}>{busy ? 'Starting…' : 'Start run'}</button></div>
  </form></dialog>;
}
