import React from 'react';
/** An implicit accessible label with optional help, shared by creative forms. */
export default function Field({ label, hint, className = '', children }) {
  return <label className={`panel-field ${className}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
