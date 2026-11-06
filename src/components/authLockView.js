// Lock screen view state (AuthLock.jsx): the status line and the camera rim.

/** @param {'looking' | 'recognized' | 'rejected'} status */
export const authLockMessage = status => (status === 'recognized' ? 'Face recognized'
    : status === 'rejected' ? 'Face not recognized. Try again.' : 'Looking for your face…');

/** The camera circle's rim: green once the face is recognised, otherwise the plain line. */
export const authLockCameraState = status => (status === 'recognized' ? 'recognized' : 'looking');
