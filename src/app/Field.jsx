import React from 'react';
import './panel-parts.css';
/** An implicit accessible label with optional help, shared by creative forms. */
export default function Field({ label, hint, className = '', children }) {
  return <label className={`panel-field ${className}`.trim()}><span className="panel-field__label">{label}</span>{children}{hint && <small className="panel-field__hint">{hint}</small>}</label>;
}
