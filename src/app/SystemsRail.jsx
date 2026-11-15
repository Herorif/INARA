import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import { createRpcScope } from '../transport/rpc.ts';
import { voiceChip } from '../features/voice/status.js';
import { useLowBattery } from '../shared/motion/materialise.js';
import HudLabel from '../shared/ui/HudLabel';
import {
  AGENDA_REFRESH_MS, GAMING_PAUSED, HOME_REFRESH_MS, RAIL_TITLES, WEATHER_REFRESH_MS,
  clockText, countdownText, dateText, msToNextMinute, normalizeVitals, pcRows, pushSample,
  remindersText, runningJobs, seriesData, seriesRange, visibleSections, watchRequest,
} from './systemsRailModel.js';
import './systemsRail.css';

const SPARK_WIDTH = 120, SPARK_HEIGHT = 24;
const FALLBACK_COLOR = '#70e0ed';
const EMPTY = [];

/** The current time, re-rendered on each minute boundary (values just update, no animation). */
function useMinute() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer = 0;
    const schedule = () => { timer = setTimeout(() => { setNow(new Date()); schedule(); }, msToNextMinute(Date.now())); };
    schedule();
    return () => clearTimeout(timer);
  }, []);
  return now;
}

function useDocumentVisible() {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return visible;
}

/** Calls `load` now and every `every` ms while `active`; the latest answer, or null. */
function usePolled(active, every, load, refreshKey) {
  const [value, setValue] = useState(null);
  useEffect(() => {
    if (!active) return undefined;
    let live = true;
    const run = () => load().then(next => { if (live) setValue(next); }, () => {});
    run();
    const timer = setInterval(run, every);
    return () => { live = false; clearInterval(timer); };
  }, [active, every, load, refreshKey]);
  return value;
}

const roleColor = () => {
  try { return getComputedStyle(document.documentElement).getPropertyValue('--role-system').trim() || FALLBACK_COLOR; } catch { return FALLBACK_COLOR; }
};

/** A 120×24 uPlot line: no axes, legend, cursor or selection; destroyed on unmount. */
function Sparkline({ series, kind }) {
  const host = useRef(null), plot = useRef(null), range = useRef(seriesRange(kind, series[1]));
  useEffect(() => {
    const chart = new uPlot({
      width: SPARK_WIDTH, height: SPARK_HEIGHT, pxAlign: false, padding: [2, 1, 2, 1],
      cursor: { show: false }, legend: { show: false }, select: { show: false },
      axes: [{ show: false }, { show: false }],
      scales: { x: { time: false }, y: { auto: false, range: () => range.current } },
      series: [{}, { stroke: roleColor(), width: 1.5, points: { show: false } }],
    }, series, host.current);
    plot.current = chart;
    return () => { chart.destroy(); plot.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    range.current = seriesRange(kind, series[1]);
    plot.current?.setData(series);
  }, [series, kind]);
  return <div ref={host} className="rail-spark" aria-hidden="true"/>;
}

function RailSection({ id, children }) {
  return <section className="rail-section" data-section={id} aria-labelledby={`rail-${id}`}>
    <HudLabel as="h2" id={`rail-${id}`} className="rail-label">{RAIL_TITLES[id]}</HudLabel>
    {children}
  </section>;
}

/**
 * The Systems rail (docs/SYSTEMS_RAIL.md) inside the context inspector: Now, Weather, Next,
 * Home, This PC, Jobs and JARVIS. Each section hides without a source. While mounted and the
 * window is visible it watches PC vitals (vitals_watch), except in gaming mode.
 */
export default function SystemsRail({ connected, gaming, voice, resource, memory, onOpen }) {
  const now = useMinute();
  const visible = useDocumentVisible();
  const lowBattery = useLowBattery(!gaming);
  const reminders = useStore(state => state.reminders);
  const activity = useStore(state => state.activity);
  const project = useStore(state => state.currentProject);
  const scope = useMemo(() => createRpcScope(socket), []);
  const [samples, setRing] = useState([]);
  const [settingsTick, setSettingsTick] = useState(0);
  const active = connected && visible;

  useEffect(() => () => scope.dispose(), [scope]);
  useEffect(() => scope.on('vitals', payload => setRing(current => pushSample(current, normalizeVitals(payload)))), [scope]);
  // A new home town in Preferences reaches every renderer as `settings`: ask for the weather again.
  useEffect(() => scope.on('settings', () => setSettingsTick(value => value + 1)), [scope]);

  // Vitals: watch while visible, connected and not gaming; the core samples and decides the rate.
  useEffect(() => {
    if (!active || gaming) return undefined;
    emitSocket('vitals_watch', watchRequest({ on: true, lowBattery }));
    return () => { emitSocket('vitals_watch', watchRequest({ on: false })); };
  }, [active, gaming, lowBattery]);

  const loadWeather = useCallback(() => scope.call('weather_now', {}), [scope]);
  const loadAgenda = useCallback(() => scope.call('agenda_next', {}), [scope]);
  const loadHome = useCallback(() => scope.call('home_summary', {}), [scope]);
  // Offline, nothing shows: the last answers stay only while the core is connected.
  const weatherNow = usePolled(active, WEATHER_REFRESH_MS, loadWeather, settingsTick);
  const agendaNow = usePolled(active, AGENDA_REFRESH_MS, loadAgenda, reminders);
  const homeNow = usePolled(active, HOME_REFRESH_MS, loadHome, 0);
  const weather = connected ? weatherNow : null, agenda = connected ? agendaNow : null, home = connected ? homeNow : null;

  const ring = connected ? samples : EMPTY;
  const jobs = runningJobs(activity, project);
  const nowMs = now.getTime();
  const sections = visibleSections({ weather, agenda, home, ring, gaming, jobs, nowMs });
  const countdown = agenda?.event ? countdownText(agenda.event.title, agenda.event.at, nowMs) : null;
  const due = agenda ? remindersText(agenda.reminders) : null;
  const pc = pcRows(ring);
  const series = useMemo(() => ({ cpu: seriesData(ring, 'cpu'), mem: seriesData(ring, 'mem'), net: seriesData(ring, 'net') }), [ring]);
  const voiceLabel = { OFF: 'Off', READY: 'Ready', LISTENING: 'Listening', SPEAKING: 'Speaking' }[voiceChip({ connected, gaming, voice })];

  const blocks = {
    now: <RailSection id="now" key="now">
      <time className="rail-clock" dateTime={now.toISOString()}>{clockText(now)}</time>
      <p className="rail-date">{dateText(now)}</p>
    </RailSection>,
    weather: <RailSection id="weather" key="weather"><p className="rail-line">{weather?.line}</p></RailSection>,
    next: <RailSection id="next" key="next">
      {countdown && <p className="rail-line rail-line--strong">{countdown}</p>}
      {due && <p className="rail-line">{due}</p>}
      {due && <button type="button" className="btn btn--ghost btn--sm rail-link" onClick={() => onOpen('reminder')}>Open reminders</button>}
    </RailSection>,
    home: <RailSection id="home" key="home"><p className="rail-line">{home?.line}</p></RailSection>,
    pc: <RailSection id="pc" key="pc">
      {gaming ? <p className="rail-line rail-paused">{GAMING_PAUSED}</p> : <>
        <ul className="rail-vitals">{pc.spark.map(row => <li key={row.key} className="rail-vital" data-vital={row.key} aria-label={row.spoken || `${row.label} ${row.value}`}>
          <span className="rail-vital__text"><span className="rail-vital__label">{row.label}</span><span className="rail-vital__value tnum">{row.parts ? row.parts.map((part, index) => <React.Fragment key={part + index}>{index > 0 && ' '}<span className="rail-nowrap">{part}</span></React.Fragment>) : row.value}</span></span>
          <Sparkline series={series[row.key]} kind={row.key}/>
        </li>)}</ul>
        {!!pc.plain.length && <dl className="rail-facts">{pc.plain.map(row => <div key={row.key} data-vital={row.key}><dt>{row.label}</dt><dd className="tnum">{row.value}</dd></div>)}</dl>}
      </>}
    </RailSection>,
    jobs: <RailSection id="jobs" key="jobs">
      <ul className="rail-jobs">{jobs.slice(0, 4).map(job => <li key={job.key}><span className="rail-jobs__name">{job.name}</span><span className="rail-jobs__phase">{job.phase}</span></li>)}</ul>
    </RailSection>,
    jarvis: <RailSection id="jarvis" key="jarvis">
      <dl className="rail-facts">
        <div><dt>Resource mode</dt><dd>{gaming ? 'Gaming' : resource.state === 'studio' ? 'Studio' : 'Lightweight'}</dd></div>
        <div><dt>Voice</dt><dd>{voiceLabel}</dd></div>
        <div><dt>Workspace memory</dt><dd className="tnum">{memory === null ? 'Not measured' : `${Math.round(memory)} MB`}</dd></div>
      </dl>
    </RailSection>,
  };
  return <div className="systems-rail" data-gaming={gaming ? 'on' : 'off'}>{sections.map(id => blocks[id])}</div>;
}
