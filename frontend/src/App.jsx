import React, { useCallback, useEffect, useState } from 'react';
import { request, runURL, fileURL } from './api.js';
import { History, Icon, Overview, Transcript, NewRun } from './components.jsx';

const tabs = ['Overview', 'Transcript', 'Selection JSON', 'Run log'];
export default function App() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(() => decodeURIComponent(location.hash.slice(1)));
  const [run, setRun] = useState(null);
  const [tab, setTab] = useState('Overview');
  const [token, setToken] = useState('');
  const [defaults, setDefaults] = useState(null);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [newRun, setNewRun] = useState(false);

  const refresh = useCallback(async () => {
    try { const data = await request('/api/runs'); setRuns(data); setLoaded(true); setError(''); } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => {
    refresh();
    request('/api/config').then(data => { setToken(data.token); setDefaults(data.defaults); }).catch(e => setError(e.message));
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (!selected && runs.length) setSelected(runs[0].id);
  }, [selected, runs]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setRun(null);
    request(runURL(selected), { signal: controller.signal }).then(setRun).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    const timer = setInterval(() => {
      request(runURL(selected), { signal: controller.signal }).then(setRun).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    }, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [selected]);

  function select(id) { setSelected(id); setTab('Overview'); setError(''); history.replaceState(null, '', `#${encodeURIComponent(id)}`); }
  return <>
    <header className="header"><a className="brand" href="/">Maho</a><span className="workspace-label">Video workspace</span><button className="primary new-run" onClick={() => setNewRun(true)}><Icon name="plus" />New run</button></header>
    <div className="workspace"><History runs={runs} selected={selected} onSelect={select} onRefresh={refresh} />
      <main>{error ? <p className="error global-error" role="alert">{error}</p> : null}
        {run ? <><div className="page-heading"><h1>{run.filename}</h1><p className="run-meta"><span className={`status-dot ${run.status}`} /><span className="status-text">{run.status}</span><span>·</span><span>{run.clip_count} clips</span><span>·</span><span>{run.created_at ? new Date(run.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Saved run'}</span></p></div>
          {run.error ? <p className="error" role="alert">{run.error}</p> : null}
          <nav className="tabs" aria-label="Run details" role="tablist">{tabs.map(name => <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>
          <div role="tabpanel" aria-label={tab}>
            {tab === 'Overview' ? <Overview key={run.id} run={run} onSelection={() => setTab('Selection JSON')} /> : null}
            {tab === 'Transcript' ? <Transcript key={run.id} run={run} /> : null}
            {tab === 'Selection JSON' ? <section className="text-view"><div className="text-toolbar"><h2>Structured selection</h2>{run.selection.clips ? <a href={fileURL(run.id, 'selection', true)} download>Download JSON</a> : null}</div><pre>{run.selection.clips ? JSON.stringify(run.selection, null, 2) : 'The AI selection will appear here when analysis completes.'}</pre></section> : null}
            {tab === 'Run log' ? <section className="text-view"><div className="text-toolbar"><h2>Run log</h2><span className="muted">Updates automatically</span></div><pre>{run.log || 'Starting the pipeline…'}</pre></section> : null}
          </div>
        </> : <div className="workspace-empty"><Icon name="film" size={42} /><h1>{!loaded || selected ? 'Loading workspace…' : 'Your video workspace'}</h1><p>{runs.length ? 'Select a previous run to inspect its input and clips.' : 'Start a run to turn a video into a collection of clips.'}</p>{loaded && !runs.length ? <button className="primary" onClick={() => setNewRun(true)}>New run</button> : null}</div>}
      </main>
    </div>
    {newRun ? <NewRun token={token} defaults={defaults} onClose={() => setNewRun(false)} onCreated={id => { select(id); refresh(); setNewRun(false); }} /> : null}
  </>;
}
