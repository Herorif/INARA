import React, { useState } from 'react';
import {
  Monitor, HardDrive, Battery, BatteryCharging,
  Search, Clipboard, ClipboardPaste, Camera, RefreshCw,
  Terminal, Code, Music, MessageSquare, Globe } from
'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import EmptyState from '../shared/ui/EmptyState';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const pct = (v) => `${Math.round(v ?? 0)}%`;

const usageState = (percent) => percent > 90 ? 'danger' : percent > 70 ? 'warn' : null;
const STATE_TEXT = { danger: 'text-danger', warn: 'text-warn' };
const STATE_FILL = { danger: 'bg-danger', warn: 'bg-warn' };
const STATE_LABEL = { danger: 'Critical', warn: 'High' };

const UsageBar = ({ label, percent }) => {
  const state = usageState(percent);
  return (
    <div className="space-y-1">
            <div className="flex justify-between gap-2 text-[0.75rem]">
                <span className="text-ink-2">{label}</span>
                <span className={`shrink-0 font-mono ${state ? STATE_TEXT[state] : 'text-ink-1'}`}>
                    {pct(percent)}{state && ` · ${STATE_LABEL[state]}`}
                </span>
            </div>
            <div className="h-1 overflow-hidden rounded-sm bg-[var(--line)]">
                <div
          className={`h-full transition-all duration-500 ${state ? STATE_FILL[state] : 'bg-accent'}`}
          style={{ width: `${Math.min(100, percent ?? 0)}%` }} />

            </div>
        </div>);

};

// ---------------------------------------------------------------------------
// Quick launch apps
// ---------------------------------------------------------------------------
const QUICK_APPS = [
{ name: 'chrome', label: 'Chrome', icon: Globe },
{ name: 'vscode', label: 'VS Code', icon: Code },
{ name: 'terminal', label: 'Terminal', icon: Terminal },
{ name: 'spotify', label: 'Spotify', icon: Music },
{ name: 'discord', label: 'Discord', icon: MessageSquare },
{ name: 'explorer', label: 'Explorer', icon: HardDrive }];


const AppButton = ({ app }) => {
  const Icon = app.icon;
  const handleLaunch = () => {
    emitSocket('launch_app', { name: app.name });
  };
  return (
    <button
      type="button"
      onClick={handleLaunch}
      className="group flex flex-col items-center gap-1.5 rounded-md border border-line bg-raised p-3 transition-colors hover:border-line-strong hover:bg-[var(--bg-hover)]">

            <Icon size={20} aria-hidden="true" className="text-ink-2 transition-colors group-hover:text-ink-1" />
            <span className="text-[0.75rem] text-ink-2 group-hover:text-ink-1">{app.label}</span>
        </button>);

};

// ---------------------------------------------------------------------------
// Stats Panel
// ---------------------------------------------------------------------------
const StatsPanel = ({ info }) => {
  if (!info) {
    return <EmptyState className="py-6" icon={<Monitor />} title="No system info yet" body="Ask JARVIS for system info, or refresh." />;
  }

  const { cpu, memory, disk = [], battery } = info;
  const lowBattery = battery && battery.percent < 20;

  return (
    <div className="space-y-3">
            {cpu &&
      <UsageBar
        label={`CPU — ${cpu.cores ?? '?'} cores${cpu.freq_mhz ? ` @ ${cpu.freq_mhz} MHz` : ''}`}
        percent={cpu.percent} />

      }
            {memory &&
      <UsageBar
        label={`RAM — ${memory.used_gb ?? '?'} / ${memory.total_gb ?? '?'} GB`}
        percent={memory.percent} />

      }
            {disk.slice(0, 2).map((d) =>
      <UsageBar
        key={d.mount}
        label={`Disk ${d.mount} — ${d.used_gb} / ${d.total_gb} GB`}
        percent={d.percent} />

      )}
            {battery &&
      <div className="flex items-center justify-between border-t border-line pt-2 text-[0.75rem]">
                    <div className="flex items-center gap-1.5 text-ink-2">
                        {battery.plugged_in ?
          <BatteryCharging size={14} aria-hidden="true" className="text-ok" /> :
          <Battery size={14} aria-hidden="true" className={lowBattery ? 'text-danger' : 'text-ink-2'} />
          }
                        <span>Battery</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={`font-mono ${lowBattery ? 'text-danger' : 'text-ink-1'}`}>
                            {battery.percent}%{lowBattery && ' · Low'}
                        </span>
                        {battery.plugged_in && <span className="text-ok">Charging</span>}
                        {!battery.plugged_in && battery.time_left_min &&
          <span className="text-ink-3">~{battery.time_left_min}m left</span>
          }
                    </div>
                </div>
      }
        </div>);

};

// ---------------------------------------------------------------------------
// Processes list
// ---------------------------------------------------------------------------
const ProcessList = ({ processes }) => {
  if (!processes || processes.length === 0) {
    return <div className="py-4 text-center text-[0.75rem] text-ink-3">No process data</div>;
  }
  return (
    <div className="space-y-0.5">
            {processes.slice(0, 8).map((p) =>
      <div key={p.pid} className="flex items-center justify-between rounded px-2 py-1 transition-colors hover:bg-[var(--bg-hover)]">
                    <span className="mr-2 flex-1 truncate font-mono text-[0.75rem] text-ink-1">{p.name}</span>
                    <div className="flex shrink-0 items-center gap-2">
                        <span className="w-16 text-right font-mono text-[0.6875rem] text-ink-3">{p.memory_mb} MB</span>
                        {p.cpu_percent > 0 &&
          <span className="w-12 text-right font-mono text-[0.6875rem] text-ink-2">{p.cpu_percent.toFixed(1)}%</span>
          }
                    </div>
                </div>
      )}
        </div>);

};

// ---------------------------------------------------------------------------
// DesktopWindow
// ---------------------------------------------------------------------------
const TABS = [{ id: 'stats', label: 'Stats' }, { id: 'apps', label: 'Apps' }, { id: 'tools', label: 'Tools' }];

const DesktopWindow = () => {
  const [tab, setTab] = useState('stats');
  const [searchQuery, setSearchQuery] = useState('');

  const systemInfo = useStore((s) => s.systemInfo);
  const lastScreenshot = useStore((s) => s.lastScreenshot);
  const runningApps = useStore((s) => s.runningApps);

  const handleAsk = (text) => useStore.getState().sendText(text);

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    handleAsk(`Search for files: ${searchQuery}`);
    setSearchQuery('');
  };

  const handleScreenshot = () => emitSocket('take_screenshot', {});
  const handleRefreshStats = () => emitSocket('get_system_info', {});

  return (
    <div
      id="desktop" className="tool-panel tool-panel--desktop">

            {/* Tabs and refresh */}
            <div className="flex items-center gap-2">
                <div className="hud-tabs flex-1" role="group" aria-label="Desktop controls">
                    {TABS.map((t) =>
          <button
            type="button"
            key={t.id}
            aria-pressed={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`hud-tab flex-1 text-sm ${tab === t.id ? 'is-active' : ''}`}>

                            {t.label}
                        </button>
          )}
                </div>
                <button
          type="button"
          onClick={handleRefreshStats}
          className="btn btn--ghost btn--sm btn--icon"
          title="Refresh system info" aria-label="Refresh system info">

                    <RefreshCw size={14} aria-hidden="true" />
                </button>
            </div>

            <div className="flex flex-1 flex-col gap-4 overflow-y-auto">

                {/* STATS TAB */}
                {tab === 'stats' &&
        <>
                        <StatsPanel info={systemInfo} />
                        {runningApps.length > 0 &&
          <section className="flex flex-col gap-2">
                                <h3 className="hud-label">Processes</h3>
                                <ProcessList processes={runningApps} />
                            </section>
          }
                    </>
        }

                {/* APPS TAB */}
                {tab === 'apps' &&
        <>
                        <div className="grid grid-cols-3 gap-2">
                            {QUICK_APPS.map((app) => <AppButton key={app.name} app={app} />)}
                        </div>
                        <section className="flex flex-col gap-2 border-t border-line pt-3">
                            <label htmlFor="desktop-launch" className="hud-label">Launch any app</label>
                            <input
              id="desktop-launch"
              type="text"
              placeholder='App name (e.g. "notepad")'
              className="w-full px-3 text-sm"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && e.target.value.trim()) {
                  handleAsk(`Launch ${e.target.value.trim()}`);
                  e.target.value = '';
                }
              }} />

                        </section>
                    </>
        }

                {/* TOOLS TAB */}
                {tab === 'tools' &&
        <div className="flex flex-col gap-4">
                        {/* Screenshot */}
                        <section className="flex flex-col gap-2">
                            <h3 className="hud-label">Screen capture</h3>
                            {lastScreenshot ?
            <figure className="m-0 overflow-hidden rounded-md border border-line">
                                    <img
                src={`data:image/jpeg;base64,${lastScreenshot}`}
                alt="Last screenshot"
                className="w-full object-cover"
                style={{ maxHeight: 140 }} />

                                    <figcaption className="border-t border-line bg-raised px-2 py-1 text-[0.75rem] text-ink-2">Last capture</figcaption>
                                </figure> :

            <EmptyState className="rounded-md border border-dashed border-line-strong py-5" icon={<Camera />} title="No capture yet" />
            }
                            <button
              type="button"
              onClick={handleScreenshot}
              className="btn btn--secondary w-full">

                                <Camera size={14} aria-hidden="true" /> Capture screen
                            </button>
                        </section>

                        {/* File search */}
                        <section className="flex flex-col gap-2 border-t border-line pt-3">
                            <label htmlFor="desktop-file-search" className="hud-label">File search</label>
                            <div className="flex gap-2">
                                <input
                id="desktop-file-search"
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder='e.g. "resume.docx" or "*.pdf"'
                className="min-w-0 flex-1 px-3 text-sm" />

                                <button
                type="button"
                onClick={handleSearch}
                disabled={!searchQuery.trim()}
                aria-label="Search files"
                className="btn btn--secondary btn--icon disabled:cursor-not-allowed disabled:opacity-40">

                                    <Search size={14} aria-hidden="true" />
                                </button>
                            </div>
                        </section>

                        {/* Clipboard */}
                        <section className="flex flex-col gap-2 border-t border-line pt-3">
                            <h3 className="hud-label">Clipboard</h3>
                            <div className="flex gap-2">
                                <button
                type="button"
                onClick={() => handleAsk('Read my clipboard')}
                className="btn btn--secondary flex-1">

                                    <Clipboard size={14} aria-hidden="true" /> Read
                                </button>
                                <button
                type="button"
                onClick={() => handleAsk('What did I last copy to clipboard?')}
                className="btn btn--secondary flex-1">

                                    <ClipboardPaste size={14} aria-hidden="true" /> Paste to JARVIS
                                </button>
                            </div>
                        </section>
                    </div>
        }
            </div>
        </div>);

};

export default DesktopWindow;
