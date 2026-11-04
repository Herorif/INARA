import React, { useState, useEffect } from 'react';
import { RefreshCw, Printer, Thermometer, Clock, FileText, ExternalLink } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import StatusChip from '../shared/ui/StatusChip';
import EmptyState from '../shared/ui/EmptyState';
import { printerWebUrl } from './printerHost';

const PrinterWindow = () => {
  const printers = useStore((s) => s.printerList);
  const slicingProgress = useStore((s) => s.slicingStatus);
  const printerSystemStatus = useStore((s) => s.printerSystemStatus);

  const [isDiscovering, setIsDiscovering] = useState(false);

  useEffect(() => {
    const onPrintResult = (result) => {
      if (result.status === 'success') {
        useStore.setState({ slicingStatus: { percent: 100, message: result.message || 'Done', active: false } });
      } else {
        useStore.setState({ slicingStatus: { percent: 0, message: result.message || 'Failed', active: false } });
      }
    };

    const done = () => setIsDiscovering(false);
    socket.on('print_result', onPrintResult);socket.on('printer_list', done);socket.on('error', done);socket.on('disconnect', done);
    return () => { socket.off('print_result', onPrintResult);socket.off('printer_list', done);socket.off('error', done);socket.off('disconnect', done); };
  }, []);

  useEffect(() => {
    if (printers.length > 0) setIsDiscovering(false);
  }, [printers]);

  const handleDiscover = () => {
    setIsDiscovering(true);
    emitSocket('discover_printers');
  };

  const getStatusTone = (state) => {
    if (!state) return 'idle';
    const s = state.toLowerCase();
    if (s.includes('print')) return 'ok';
    if (s.includes('offline')) return 'idle';
    if (s.includes('paus')) return 'warn';
    if (s.includes('error') || s.includes('fail')) return 'danger';
    return 'accent';
  };

  const addPrinter = (ipInput, nameInput) => {
    const ip = ipInput?.value.trim();
    const name = nameInput?.value.trim() || ip;
    if (ip) {
      emitSocket('add_printer', { host: ip, name, type: 'moonraker' });
      if (ipInput) ipInput.value = '';
      if (nameInput) nameInput.value = '';
      setIsDiscovering(true);
    }
  };

  const openExternal = (url) => {
    if (window.electronAPI) {
      window.electronAPI.openExternal(url);
    }
  };

  return (
    <div
      id="printer" className="tool-panel tool-panel--printer">

            <div className="flex items-center justify-between gap-2">
                {printerSystemStatus ?
        <StatusChip tone={printerSystemStatus.available ? 'ok' : 'warn'}>
                        {printerSystemStatus.available ? 'Printing ready' : 'Printing unavailable'}
                    </StatusChip> :
        <span />}
                <button type="button" onClick={handleDiscover} disabled={isDiscovering}
        className="btn btn--ghost btn--sm btn--icon disabled:cursor-not-allowed" aria-label="Discover printers" title="Discover printers">
                    <RefreshCw size={14} aria-hidden="true" className={isDiscovering ? 'animate-spin' : ''} />
                </button>
            </div>

            {printerSystemStatus?.message &&
      <p className="text-[0.8125rem] leading-relaxed text-ink-2">{printerSystemStatus.message}</p>
      }

            <section className="flex flex-col gap-2 rounded-md border border-line bg-raised p-3">
                <h3 className="hud-label">Add a printer manually</h3>
                <input id="printer-name-input" type="text" placeholder="Printer name (e.g. Creality K1)"
        className="w-full px-2 text-sm" aria-label="Printer name" />
                <div className="flex gap-2">
                    <input id="printer-ip-input" type="text" placeholder="IP address (e.g. 192.168.1.50)"
          className="min-w-0 flex-1 px-2 font-mono text-sm"
          onKeyDown={(e) => {
            if (e.key === 'Enter') addPrinter(e.target, document.getElementById('printer-name-input'));
          }} aria-label="IP address" />

                    <button type="button" className="btn btn--secondary"
          onClick={() => addPrinter(document.getElementById('printer-ip-input'), document.getElementById('printer-name-input'))}>
                        Add
                    </button>
                </div>
            </section>

            {printers.length === 0 ?
      isDiscovering ?
      <div className="flex flex-col items-center gap-2 py-8 text-sm text-ink-2" role="status">
                        <RefreshCw className="animate-spin" size={20} aria-hidden="true" />
                        <span>Scanning network…</span>
                    </div> :
      <EmptyState className="py-8" icon={<Printer />} title="No printers found" body="Discover printers on your network, or add one by IP address." /> :

      <div className="flex flex-col gap-3">
                    {slicingProgress.active &&
        <section className="rounded-md border border-line bg-raised p-3">
                            <div className="mb-2 flex justify-between gap-2">
                                <h3 className="hud-label">Preparation pipeline</h3>
                                <span className="font-mono text-[0.6875rem] text-ink-1">{slicingProgress.percent}%</span>
                            </div>
                            <div className="mb-2 flex items-center gap-2 text-[0.75rem] text-ink-3">
                                <div className={`flex items-center gap-1.5 ${slicingProgress.percent < 100 ? 'text-ink-1' : ''}`}>
                                    <span className={`status-dot ${slicingProgress.percent < 100 ? 'status-dot--accent' : ''}`} aria-hidden="true" />
                                    Slicing
                                </div>
                                <div className="h-px w-4 bg-[var(--line-strong)]" aria-hidden="true" />
                                <div className="flex items-center gap-1.5">
                                    <span className="status-dot" aria-hidden="true" />
                                    Printing
                                </div>
                            </div>
                            <div className="h-1 w-full overflow-hidden rounded-sm bg-[var(--line)]">
                                <div className="h-full bg-accent transition-all duration-300" style={{ width: `${slicingProgress.percent}%` }} />
                            </div>
                            <div className="mt-1.5 truncate text-[0.75rem] text-ink-2">{slicingProgress.message}</div>
                        </section>
        }

                    {printers.map((printer, idx) => {
          // Discovered hosts are untrusted: only private-LAN addresses get a web link.
          const webUrl = printerWebUrl(printer.host);
          return (
            <article key={idx} className="rounded-md border border-line bg-raised p-3 transition-colors hover:border-line-strong">
                                <div className="mb-2 flex items-start justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="truncate text-sm font-medium text-ink-1">{printer.name}</div>
                                        <div className="truncate font-mono text-[0.6875rem] text-ink-3">{printer.host}:{printer.port} · {printer.printer_type}</div>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                        {webUrl ?
                <button type="button" onClick={() => openExternal(webUrl)}
                className="btn btn--secondary btn--sm"
                title={`Open printer web interface at ${webUrl}`} aria-label={`Open printer web interface at ${webUrl}`}>
                                                <ExternalLink size={12} aria-hidden="true" />
                                                <span>Open</span>
                                            </button> :
                <span className="text-[0.6875rem] text-ink-3">Not a local address</span>
                }
                                        {printer.status &&
                <StatusChip tone={getStatusTone(printer.status.state)}>{printer.status.state || 'Idle'}</StatusChip>
                }
                                    </div>
                                </div>

                                {printer.camera_url &&
              <div className="relative mb-3 aspect-video overflow-hidden rounded border border-line bg-canvas">
                                        <img src={printer.camera_url} alt="Printer camera" className="h-full w-full object-cover"
                onError={(e) => {e.target.style.display = 'none';e.target.nextSibling.style.display = 'flex';}} />
                                        <div className="absolute inset-0 hidden items-center justify-center text-[0.75rem] text-ink-3">
                                            Camera stream unavailable
                                        </div>
                                    </div>
              }

                                {printer.status &&
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                                        {printer.status.details &&
                <div className="text-[0.75rem] text-ink-2">
                                                {printer.status.details}
                                            </div>
                }
                                        {printer.status.progress_percent > 0 &&
                <div className="h-1 w-full overflow-hidden rounded-sm bg-[var(--line)]">
                                                <div className="h-full bg-accent transition-all duration-500" style={{ width: `${printer.status.progress_percent}%` }} />
                                            </div>
                }
                                        <div className="grid grid-cols-2 gap-2 text-[0.75rem] text-ink-2">
                                            {printer.status.filename &&
                  <div className="col-span-2 flex items-center gap-1.5 truncate">
                                                    <FileText size={12} aria-hidden="true" className="shrink-0 text-ink-3" />
                                                    <span className="truncate font-mono">{printer.status.filename}</span>
                                                </div>
                  }
                                            {printer.status.temperatures?.hotend &&
                  <div className="flex items-center gap-1.5">
                                                    <Thermometer size={12} aria-hidden="true" className="text-ink-3" />
                                                    <span>Hotend <span className="font-mono text-ink-1">{Math.round(printer.status.temperatures.hotend.current)}°C</span></span>
                                                </div>
                  }
                                            {printer.status.temperatures?.bed &&
                  <div className="flex items-center gap-1.5">
                                                    <Thermometer size={12} aria-hidden="true" className="text-ink-3" />
                                                    <span>Bed <span className="font-mono text-ink-1">{Math.round(printer.status.temperatures.bed.current)}°C</span></span>
                                                </div>
                  }
                                            {printer.status.time_remaining &&
                  <div className="flex items-center gap-1.5">
                                                    <Clock size={12} aria-hidden="true" className="text-ink-3" />
                                                    <span><span className="font-mono text-ink-1">{printer.status.time_remaining}</span> left</span>
                                                </div>
                  }
                                        </div>
                                    </div>
              }
                            </article>);
        })}
                </div>
      }
        </div>);

};

export default PrinterWindow;
