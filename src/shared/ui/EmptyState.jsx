import React from 'react';

/** Centered empty state: optional icon element, title, body copy and action element. */
export default function EmptyState({ icon = null, title, body, action = null, className = '', ...rest }) {
  return <div className={`empty-state ${className}`.trim()} {...rest}>
    {icon && <span className="empty-state__icon" aria-hidden="true">{icon}</span>}
    {title && <p className="empty-state__title">{title}</p>}
    {body && <p className="empty-state__body">{body}</p>}
    {action && <div className="empty-state__action">{action}</div>}
  </div>;
}
