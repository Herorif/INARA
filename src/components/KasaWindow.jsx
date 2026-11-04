import React, { useState, useEffect } from 'react';
import { RefreshCw, Power, Sun, Palette, Lightbulb } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import StatusChip from '../shared/ui/StatusChip';
import EmptyState from '../shared/ui/EmptyState';

// The hue slider's spectrum is the control's content (it shows which color each position sets).
const HUE_TRACK = 'linear-gradient(to right, red, yellow, lime, cyan, blue, magenta, red)';

const KasaWindow = () => {
  const devices = useStore((s) => s.kasaDevices);
  const [isThinking, setIsThinking] = useState(false);
  const [loadingDevices, setLoadingDevices] = useState({});

  useEffect(() => {
    const onUpdate = (data) => {
      if (data && data.ip) {
        setLoadingDevices((prev) => {
          const next = { ...prev };
          delete next[data.ip];
          return next;
        });
      }
    };
    const done = () => setIsThinking(false);
    const failed = () => { setIsThinking(false); setLoadingDevices({}); };
    socket.on('kasa_update', onUpdate);socket.on('kasa_devices', done);socket.on('error', failed);socket.on('disconnect', failed);
    return () => { socket.off('kasa_update', onUpdate);socket.off('kasa_devices', done);socket.off('error', failed);socket.off('disconnect', failed); };
  }, []);

  const handleDiscover = () => {
    setIsThinking(true);
    emitSocket('discover_kasa');
  };

  useEffect(() => {
    if (devices && devices.length > 0) setIsThinking(false);
  }, [devices]);

  const handleToggle = (ip, currentState) => {
    setLoadingDevices((prev) => ({ ...prev, [ip]: true }));
    emitSocket('control_kasa', { ip, action: currentState ? 'off' : 'on' });
  };

  const handleBrightness = (ip, val) => {
    emitSocket('control_kasa', { ip, action: 'brightness', value: parseInt(val) });
  };

  const handleColor = (ip, hue) => {
    emitSocket('control_kasa', { ip, action: 'color', value: { h: parseInt(hue), s: 100, v: 100 } });
  };

  return (
    <div
      id="kasa" className="tool-panel tool-panel--kasa">

            <div className="flex items-center justify-between gap-2">
                <StatusChip tone="idle">
                    {devices.length > 0 ? `${devices.length} observed` : 'No devices'}
                </StatusChip>
                {devices.length > 0 &&
        <button type="button" onClick={handleDiscover} className="btn btn--ghost btn--sm btn--icon" title="Rescan" aria-label="Rescan for lights">
                        <RefreshCw size={14} aria-hidden="true" />
                    </button>
        }
            </div>

            <div className="flex flex-1 flex-col gap-3">
                {devices.length === 0 && !isThinking &&
        <EmptyState
          className="py-8"
          icon={<Lightbulb />}
          title="No observed devices"
          body="Discovery starts only when you request it."
          action={
          <button type="button" onClick={handleDiscover} className="btn btn--secondary btn--sm">
                                <RefreshCw size={14} aria-hidden="true" /> Discover lights
                            </button>
          } />

        }

                {isThinking &&
        <div className="flex flex-col items-center justify-center gap-3 p-8" role="status">
                        <RefreshCw size={20} aria-hidden="true" className="animate-spin text-ink-2" />
                        <span className="text-sm text-ink-2">Scanning network…</span>
                    </div>
        }

                {devices.map((dev) =>
        <article key={dev.ip} className="rounded-md border border-line bg-raised p-3 transition-colors hover:border-line-strong">
                        <div className="flex items-center justify-between gap-3">
                            <div className="flex min-w-0 flex-col gap-1">
                                <span className="truncate text-sm font-medium text-ink-1">{dev.alias}</span>
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="font-mono text-[0.6875rem] text-ink-3">{dev.ip}</span>
                                    {dev.online === false ?
                <StatusChip tone="warn">Offline or unverified</StatusChip> :
                <StatusChip tone="idle">Cached observation</StatusChip>
                }
                                </div>
                            </div>
                            <button
              type="button"
              onClick={() => handleToggle(dev.ip, dev.is_on)}
              disabled={loadingDevices[dev.ip] || dev.online === false}
              aria-pressed={!!dev.is_on}
              aria-label={`Power ${dev.alias}`}
              className={`btn btn--secondary btn--icon shrink-0 disabled:cursor-not-allowed disabled:opacity-50 ${dev.is_on ? '!border-[color:var(--ok)] !text-ok' : ''}`}>

                                {loadingDevices[dev.ip] ?
              <RefreshCw size={16} aria-hidden="true" className="animate-spin" /> :
              <Power size={16} aria-hidden="true" />
              }
                            </button>
                        </div>

                        {dev.has_brightness && dev.is_on &&
          <div className="mt-3 flex items-center gap-2">
                                <Sun size={14} aria-hidden="true" className="shrink-0 text-ink-3" />
                                <input type="range" min="0" max="100" defaultValue={dev.brightness || 100}
            onChange={(e) => handleBrightness(dev.ip, e.target.value)}
            aria-label={`${dev.alias} brightness`}
            className="w-full cursor-pointer accent-accent" />

                            </div>
          }

                        {dev.has_color && dev.is_on &&
          <div className="mt-3 flex items-center gap-2">
                                <Palette size={14} aria-hidden="true" className="shrink-0 text-ink-3" />
                                <input type="range" min="0" max="360" defaultValue={dev.hsv && dev.hsv.h || 0}
            onChange={(e) => handleColor(dev.ip, e.target.value)}
            aria-label={`${dev.alias} color`}
            className="h-1.5 w-full cursor-pointer appearance-none rounded-full [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-[color:var(--bg-canvas)] [&::-webkit-slider-thumb]:bg-ink-1"
            style={{ background: HUE_TRACK }} />

                            </div>
          }
                    </article>
        )}
            </div>
        </div>);

};

export default KasaWindow;
