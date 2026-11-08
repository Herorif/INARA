import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AirVent, Blinds, Check, Fan, Home, Lightbulb, Lock, MoreHorizontal, RefreshCw, ScrollText,
  ShieldCheck, Sparkles, ToggleRight, Tv,
} from 'lucide-react';
import socket from '../../services/socket';
import useStore from '../../store';
import EmptyState from '../../shared/ui/EmptyState';
import HudLabel from '../../shared/ui/HudLabel';
import { createHomeClient } from './homeClient.js';
import { ACCESS_OPTIONS, homeView, withAccess, withDevice } from './homeModel.js';
import './home.css';

const ICONS = {
  light: Lightbulb, switch: ToggleRight, input_boolean: ToggleRight, fan: Fan, climate: AirVent,
  media_player: Tv, lock: Lock, cover: Blinds, alarm_control_panel: ShieldCheck, scene: Sparkles,
  script: ScrollText,
};

/** The tile's JARVIS access menu: three choices, keyboard and pointer. */
function AccessMenu({ tile, onChoose }) {
  const [open, setOpen] = useState(false);
  const root = useRef(null);
  const button = useRef(null);
  const items = useRef([]);
  const menuId = `home-access-${tile.id.replace(/[^a-z0-9_]/g, '-')}`;

  useEffect(() => {
    if (!open) return undefined;
    const current = Math.max(0, ACCESS_OPTIONS.findIndex((option) => option.id === tile.access.value));
    items.current[current]?.focus();
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open, tile.access.value]);

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };
  const onKeyDown = (event) => {
    const index = items.current.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      items.current[(index + step + ACCESS_OPTIONS.length) % ACCESS_OPTIONS.length]?.focus();
    } else if (event.key === 'Home') { event.preventDefault(); items.current[0]?.focus(); }
    else if (event.key === 'End') { event.preventDefault(); items.current[ACCESS_OPTIONS.length - 1]?.focus(); }
    else if (event.key === 'Tab') close(false);
  };

  return <div className="home-tile__menu" ref={root}>
    <button ref={button} type="button" className="btn btn--ghost btn--sm btn--icon" aria-label={tile.menuLabel}
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      onClick={() => setOpen((value) => !value)}>
      <MoreHorizontal size={16} aria-hidden="true" />
    </button>
    {open && <div id={menuId} role="menu" aria-label={tile.menuLabel} className="home-menu" onKeyDown={onKeyDown}>
      {ACCESS_OPTIONS.map((option, index) => {
        const checked = option.id === tile.access.value;
        return <button key={option.id} ref={(node) => { items.current[index] = node; }} type="button" role="menuitemradio"
          aria-checked={checked} tabIndex={-1} className={`home-menu__item home-menu__item--${option.id}`}
          onClick={() => { close(); if (!checked) onChoose(option.id); }}>
          <span className="home-menu__check" aria-hidden="true">{checked && <Check size={14} />}</span>
          <span>{option.label}</span>
        </button>;
      })}
    </div>}
  </div>;
}

function Brightness({ tile, onCommit }) {
  const [value, setValue] = useState(tile.brightness.value);
  const sent = useRef(tile.brightness.value);
  useEffect(() => { setValue(tile.brightness.value); sent.current = tile.brightness.value; }, [tile.brightness.value]);
  const commit = () => {
    if (value === sent.current) return;
    sent.current = value;
    onCommit(value);
  };
  return <div className="home-tile__brightness">
    <input type="range" min="1" max="100" value={value} aria-label={tile.brightness.label} disabled={tile.brightness.disabled}
      style={{ '--level': `${value}%` }} onChange={(event) => setValue(Number(event.target.value))}
      onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
    <span className="home-tile__level tnum" aria-hidden="true">{value}%</span>
  </div>;
}

function Tile({ tile, onControl, onAccess }) {
  const Icon = ICONS[tile.icon] || Home;
  return <article className={`home-tile ${tile.toggle?.on ? 'is-on' : ''}`} data-entity={tile.id} aria-label={tile.name}>
    <div className="home-tile__top">
      <span className="home-tile__icon" aria-hidden="true"><Icon size={18} strokeWidth={1.6} /></span>
      <div className="home-tile__text">
        <span className="home-tile__name">{tile.name}</span>
        <span className="home-tile__state">{tile.stateText}</span>
      </div>
      {tile.toggle && <button type="button" role="switch" aria-checked={tile.toggle.on} aria-label={tile.toggle.label}
        disabled={tile.toggle.disabled} className={`home-switch ${tile.toggle.on ? 'is-on' : ''}`}
        onClick={() => onControl(tile.id, tile.toggle.on ? 'turn_off' : 'turn_on')}>
        <span aria-hidden="true" />
      </button>}
    </div>
    {tile.climate && <div className="home-tile__climate">
      {tile.climate.setPoint && <span className="home-tile__setpoint tnum">{tile.climate.setPoint}</span>}
      {tile.climate.mode && <span className="home-tile__mode">{tile.climate.mode}</span>}
    </div>}
    {tile.brightness && <Brightness tile={tile} onCommit={(value) => onControl(tile.id, 'set_brightness', value)} />}
    <div className="home-tile__foot">
      <span className="home-tile__access" data-tone={tile.access.tone}>{tile.access.text}</span>
      <AccessMenu tile={tile} onChoose={(access) => onAccess(tile.id, access)} />
    </div>
  </article>;
}

/**
 * Home (docs/HOME_ASSISTANT.md): Home Assistant rooms as HUD-labelled groups of tiles, and the
 * Kasa group (`kasa`) working as before. The owner's own tile controls act at once.
 */
export default function HomeView({ kasa, onOpen }) {
  const online = useStore((s) => s.backendConnected);
  const status = useStore((s) => s.homeStatus || null);
  const list = useStore((s) => s.homeDevices || null);
  const client = useMemo(() => createHomeClient(socket), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState({});
  const connected = !!status?.connected;
  const view = homeView(status, list, { busy, error, online, pending });

  useEffect(() => () => client.dispose(), [client]);
  const refresh = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const { list: fresh, status: value } = await client.devices();
      useStore.setState({ homeStatus: value, homeDevices: fresh });
    } catch (failure) {
      setError(failure?.message || 'Home Assistant could not be read. Try again.');
    } finally {
      setBusy(false);
    }
  }, [client]);
  useEffect(() => {
    if (!online) return;
    if (!useStore.getState().homeStatus) {
      client.status().then((value) => useStore.setState({ homeStatus: value })).catch(() => {});
    }
  }, [client, online]);
  useEffect(() => {
    if (online && connected) refresh();
  }, [online, connected, refresh]);

  const control = async (entityId, action, value) => {
    setPending((current) => ({ ...current, [entityId]: true }));
    setError('');
    try {
      const device = await client.control(entityId, action, value);
      useStore.setState((state) => ({ homeDevices: withDevice(state.homeDevices, device) }));
    } catch (failure) {
      setError(failure?.message || 'That device could not be changed. Try again.');
    } finally {
      setPending((current) => { const next = { ...current }; delete next[entityId]; return next; });
    }
  };
  const access = async (entityId, choice) => {
    setError('');
    try {
      await client.setAccess(entityId, choice);
      useStore.setState((state) => ({ homeDevices: withAccess(state.homeDevices, entityId, choice) }));
    } catch (failure) {
      setError(failure?.message || "JARVIS's access could not be changed. Try again.");
    }
  };

  return <div className="home-view">
    {view.connected && <div className="home-view__bar">
      <p className="home-view__line">{view.line}</p>
      <button type="button" className="btn btn--secondary btn--sm" onClick={refresh} disabled={view.refresh.disabled}>
        <RefreshCw size={14} aria-hidden="true" className={busy ? 'animate-spin' : ''} />
        <span>{view.refresh.label}</span>
      </button>
    </div>}
    {view.error && <p className="home-view__error" role="alert">{view.error}</p>}
    {view.empty && <EmptyState className="home-view__empty" icon={<Home />} title={view.empty.title} body={view.empty.body}
      action={<button type="button" className="btn btn--secondary btn--sm" onClick={() => onOpen?.('connections')}>{view.empty.action}</button>} />}
    {view.loading && <p className="home-view__loading" role="status">Reading your devices…</p>}
    {view.rooms.map((room) => <section key={room.name} className="home-room" aria-label={room.name}>
      <HudLabel as="h3" className="home-room__label">{room.name}</HudLabel>
      <div className="home-room__grid">
        {room.tiles.map((tile) => <Tile key={tile.id} tile={tile} onControl={control} onAccess={access} />)}
      </div>
    </section>)}
    {kasa && <section className="home-room home-room--kasa" aria-label="Kasa">
      <HudLabel as="h3" className="home-room__label">Kasa</HudLabel>
      {kasa}
    </section>}
  </div>;
}
