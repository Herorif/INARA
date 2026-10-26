"""TwiML documents built with ElementTree (attribute and text values are escaped)."""

from xml.etree.ElementTree import Element, SubElement, tostring

CONTENT_TYPE = "text/xml; charset=utf-8"

# Placeholder wording until the call-mode scripts land (C2/C3).
UNAVAILABLE_MESSAGE = "Sorry, this line can't take calls right now. Please try again later."
VOICEMAIL_MESSAGE = (
    "You've reached INARA, an AI assistant. The owner can't take this call right now. "
    "Please leave a message after the tone."
)
VOICEMAIL_THANKS = "Thank you. Goodbye."
VOICEMAIL_MAX_SECONDS = 120


def _document(root):
    return ('<?xml version="1.0" encoding="UTF-8"?>' + tostring(root, encoding="unicode")).encode(
        "utf-8"
    )


def reject(reason="rejected"):
    root = Element("Response")
    SubElement(root, "Reject", {"reason": reason})
    return _document(root)


def say_and_hangup(message=UNAVAILABLE_MESSAGE):
    root = Element("Response")
    SubElement(root, "Say").text = message
    SubElement(root, "Hangup")
    return _document(root)


def voicemail(message=VOICEMAIL_MESSAGE, max_seconds=VOICEMAIL_MAX_SECONDS):
    """Greeting, one recording, hang up.

    ``<Record>`` has no ``action``, so Twilio POSTs the recording result back to
    this same inbound URL; the gateway recognises ``RecordingSid`` and answers
    with ``thanks()`` instead of starting another recording.
    """
    root = Element("Response")
    SubElement(root, "Say").text = message
    SubElement(
        root,
        "Record",
        {"maxLength": str(int(max_seconds)), "playBeep": "true", "timeout": "5", "finishOnKey": "#"},
    )
    SubElement(root, "Hangup")
    return _document(root)


def hangup():
    root = Element("Response")
    SubElement(root, "Hangup")
    return _document(root)


def thanks():
    return say_and_hangup(VOICEMAIL_THANKS)


def connect_stream(url, parameters):
    """``<Connect><Stream>`` (bidirectional Media Stream) with custom parameters.

    Twilio forbids query strings on Stream URLs, so the per-call token travels as
    a ``<Parameter>`` and returns in the ``start`` message's customParameters.
    When the WebSocket closes, the call continues after ``</Connect>``: nothing
    follows, so the call ends.
    """
    root = Element("Response")
    connect = SubElement(root, "Connect")
    stream = SubElement(connect, "Stream", {"url": url})
    for name, value in parameters.items():
        SubElement(stream, "Parameter", {"name": str(name), "value": str(value)})
    return _document(root)


def empty():
    return _document(Element("Response"))
