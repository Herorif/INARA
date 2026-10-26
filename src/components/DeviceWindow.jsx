import React, { useState } from 'react';
import { Cpu, Power, RefreshCw, Lightbulb, Thermometer, Volume2, Tv, ToggleLeft } from 'lucide-react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import StatusChip from '../shared/ui/StatusChip';
import EmptyState from '../shared/ui/EmptyState';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const DOMAIN_ICONS = {
  light: Lightbulb,
  switch: ToggleLeft,
  input_boolean: ToggleLeft,
  climate: Thermometer,
  media_player: Tv,
  fan: Volume2,
  kasa: Lightbulb
};

const isOn = (device) => {
  const s = (device.state || '').toLowerCase();
  return s === 'on' || s === 'true' || s === 'playing';
};

// ---------------------------------------------------------------------------
// DeviceRow
// ---------------------------------------------------------------------------
const DeviceRow = ({ device }) => {
  const on = isOn(device);
  const domain = device.domain || device.type || 'default';
  const Icon = DOMAIN_ICONS[domain] || Cpu;

  const handleToggle = () => {
    emitSocket('control_device', {
      device_id: device.id,
      action: on ? 'turn_off' : 'turn_on'
    });
  };

  return (
    <div className="flex items-center gap-3 rounded-md border border-transparent px-2 py-2 transition-colors hover:border-line hover:bg-[var(--bg-hover)]">
            <div className="rounded-md border border-line bg-raised p-1.5 text-ink-2">
                <Icon size={14} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-ink-1">{device.name}</div>
                <div className="mt-1 flex items-center gap-1.5">
                    <span className="rounded border border-line px-1 font-mono text-[0.6875rem] text-ink-3">
                        {device.source === 'home_assistant' ? 'HA' : (device.source || 'N/A').toUpperCase()}
                    </span>
                    <StatusChip tone={on ? 'ok' : 'idle'}>{device.state || 'unknown'}</StatusChip>
                </div>
            </div>
            <button
        type="button"
        onClick={handleToggle}
        aria-pressed={on}
        className={`btn btn--secondary btn--sm btn--icon ${on ? '!text-ok' : ''}`}
        aria-label={`Power ${device.name}`}>

                <Power size={14} aria-hidden="true" />
            </button>
        </div>);

};

// ---------------------------------------------------------------------------
// DeviceWindow
// ---------------------------------------------------------------------------
const DeviceWindow = ({ position, onClose, onMouseDown, zIndex, activeDragElement }) => {
  const [filter, setFilter] = useState('all');

  const allDevices = useStore((s) => s.allDevices);

  const handleRefresh = () => emitSocket('list_all_devices', {});

  const FILTERS = [
  { id: 'all', label: 'All' }, { id: 'light', label: 'Lights' }, { id: 'switch', label: 'Switches' },
  { id: 'climate', label: 'Climate' }, { id: 'media', label: 'Media' }];

  const filtered = allDevices.filter((d) => {
    if (filter === 'all') return true;
    if (filter === 'media') return d.domain === 'media_player';
    return d.domain === filter || d.type === filter || d.source === filter;
  });

  const onCount = filtered.filter(isOn).length;

  return (
    <div
      id="device" className="tool-panel tool-panel--device">

            {/* Status and refresh */}
            <div className="flex items-center justify-between gap-2">
                {allDevices.length > 0 ?
        <StatusChip tone="idle">{onCount}/{allDevices.length} on</StatusChip> :
        <span />}
                <button
          type="button"
          onClick={handleRefresh}
          className="btn btn--ghost btn--sm btn--icon"
          title="Refresh device list" aria-label="Refresh device list">

                    <RefreshCw size={14} aria-hidden="true" />
                </button>
            </div>

            {/* Filters */}
            <div className="flex gap-1 overflow-x-auto" role="group" aria-label="Filter devices">
                {FILTERS.map((f) =>
        <button
          type="button"
          key={f.id}
          onClick={() => setFilter(f.id)}
          aria-pressed={filter === f.id}
          className={`btn btn--sm shrink-0 ${filter === f.id ?
          '!border-[color:var(--line-accent)] bg-[var(--accent-subtle)] text-accent' :
          'btn--ghost'}`}>

                        {f.label}
                    </button>
        )}
            </div>

            <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
                {filtered.length === 0 ?
        <EmptyState
          className="py-10"
          icon={<Cpu />}
          title={allDevices.length === 0 ? 'No devices listed' : 'No devices in this category'}
          body={allDevices.length === 0 ? 'Ask INARA to list devices, or discover them now.' : null}
          action={allDevices.length === 0 &&
          <button type="button" onClick={handleRefresh} className="btn btn--secondary btn--sm">
                                Discover devices
                            </button>
          } /> :

        filtered.map((d) => <DeviceRow key={d.id} device={d} />)
        }
            </div>

            {/* Quick commands */}
            {allDevices.length > 0 &&
      <div className="flex gap-2 border-t border-line pt-3">
                    <button
          type="button"
          onClick={() => useStore.getState().sendText('Turn off all lights')}
          className="btn btn--secondary btn--sm flex-1">

                        All lights off
                    </button>
                    <button
          type="button"
          onClick={() => useStore.getState().sendText('Turn on all lights')}
          className="btn btn--secondary btn--sm flex-1">

                        All lights on
                    </button>
                </div>
      }
        </div>);

};

export default DeviceWindow;
