import { useEffect, useState } from 'react';
import { Bell, Plus, Trash2, Clock3, ArrowUpRight } from 'lucide-react';
import useStore from '../../store';
import socket, { emitSocket } from '../../services/socket';
import './reminders.css';
export default function ReminderPanel() {
  const reminders = useStore(state => state.reminders);
  const connected = useStore(state => state.backendConnected);
  const [creating, setCreating] = useState(false),
    [task, setTask] = useState(''),
    [when, setWhen] = useState('');
  const [recurring, setRecurring] = useState(''),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState('');
  useEffect(() => {
    emitSocket('get_reminders');
    const updated = result => {
      setBusy(false);
      setMessage(result.message || 'Reminder updated.');
      if (result.success) {
        setCreating(false);
        setTask('');
        setWhen('');
      }
    };
    const failed = result => {
      setBusy(false);
      setMessage(result.msg || 'The reminder could not be updated.');
    };
    socket.on('reminder_updated', updated);
    socket.on('error', failed);
    return () => {
      socket.off('reminder_updated', updated);
      socket.off('error', failed);
    };
  }, []);
  return <div className="reminder-panel"><div className="reminder-toolbar"><div><span className="eyebrow">A LITTLE LESS TO REMEMBER</span><h3>Make space in your mind.</h3></div>
        <button className="primary-button" disabled={!connected} onClick={() => setCreating(!creating)}><Plus size={16} />{creating ? 'Hide form' : 'Add reminder'}</button></div>
        {creating && <form className="reminder-create" onSubmit={event => {
      event.preventDefault();
      setBusy(true);
      setMessage('');
      emitSocket('create_reminder', {
        task,
        when,
        recurring: recurring || null,
        timezone: 'Asia/Kuala_Lumpur'
      });
    }}>
            <label>What should I remind you about?<input required maxLength={2000} value={task} onChange={event => setTask(event.target.value)} placeholder="A moment worth remembering" /></label>
            <div className="reminder-form-grid"><label>When · Kuala Lumpur<input required type="datetime-local" value={when} onChange={event => setWhen(event.target.value)} /></label>
                <label>Repeat<select value={recurring} onChange={event => setRecurring(event.target.value)}><option value="">Just once</option><option value="daily">Every day</option><option value="weekdays">Weekdays</option><option value="weekly">Every week</option></select></label></div>
            <button className="primary-button" disabled={busy || !connected}>{busy ? 'Awaiting confirmation…' : 'Save reminder'}</button></form>}
        {message && <p role="status" className="reminder-feedback">{message}</p>}
        <div className="reminder-list">{reminders.length ? reminders.map(reminder => <article className="reminder-item" key={reminder.id}><span className="reminder-item-icon"><Bell size={18} /></span>
            <div><h4>{reminder.task}</h4><p><Clock3 size={12} />{new Date(reminder.trigger_at * 1000).toLocaleString([], {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              timeZone: reminder.timezone || 'Asia/Kuala_Lumpur'
            })}
                {reminder.recurring && <span className="reminder-repeat">{reminder.recurring}</span>}</p></div>
            <button className="icon-button" aria-label={`Cancel reminder: ${reminder.task}`} disabled={!connected} onClick={() => emitSocket('cancel_reminder', {
          reminder_id: reminder.id
        })}><Trash2 size={16} /></button></article>) : <div className="reminder-empty"><div className="welcome-mark"><Bell size={27} /></div><h3>A clear horizon.</h3><p>Set a reminder and leave the remembering to INARA.<br />Local scheduling works without an AI connection.</p></div>}</div>
        <footer className="reminder-panel-footer"><span>Schedules are saved privately on this laptop.</span><button className="text-button" onClick={() => useStore.setState({
        showReminderWindow: false,
        showRoutineWindow: true
      })}>Advanced routines <ArrowUpRight size={14} /></button></footer>
    </div>;
}
