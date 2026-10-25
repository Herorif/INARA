import React from 'react';

/** Keyboard shortcut hint. */
export default function Kbd({ className = '', children, ...rest }) {
  return <kbd className={`kbd ${className}`.trim()} {...rest}>{children}</kbd>;
}
