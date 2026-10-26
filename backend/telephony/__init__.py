"""Telephony gateway (C1): Twilio webhooks and Media Streams behind a Cloudflare tunnel.

Nothing here runs unless ``calls.enabled`` is true. The gateway is its own
loopback listener (never the core Socket.IO port); every HTTP request and the
Media Stream upgrade must carry a valid ``X-Twilio-Signature``. See
docs/CALL_ROUTING.md ("Implementation status (C1)").
"""
