"""Fixed GET-only adapter. DNS is checked and the TLS connection pins a checked IP.

No browser profile, proxy, JavaScript, cookies, forms, downloads or provider calls.
Page text is hostile data. This module never interprets instructions from it.
"""

import http.client
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from services.browser_contracts import public_url, BrowserReport

MAX_BYTES = 524288


class PageText(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.hidden, self.in_title = url, [], False
        self.parts, self.title, self.links = [], [], []
        self.size = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "title":
            self.in_title = True
        if tag == "a" and len(self.links) < 30:
            try:
                target = public_url(urljoin(self.url, dict(attrs).get("href", "")))
                if len(target) <= 2048 and target not in self.links:
                    self.links.append(target)
            except (ValueError, UnicodeError):
                pass

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.hidden:
            return
        value = " ".join(data.split())
        if self.in_title and sum(map(len, self.title)) < 240:
            self.title.append(value[:240])
        if value and self.size < 12000:
            value = value[: 12000 - self.size]
            self.parts.append(value)
            self.size += len(value) + 1

    def report(self):
        return BrowserReport(
            url=self.url,
            title=" ".join(self.title)[:240],
            text="\n".join(self.parts)[:12000],
            links=self.links,
        ).model_dump()


def public_addresses(host):
    addresses = list(
        dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    )
    if not addresses or any(
        not ipaddress.ip_address(ip).is_global
        or ipaddress.ip_address(ip).is_multicast
        or ipaddress.ip_address(ip).is_reserved
        for ip in addresses
    ):
        raise ValueError("Private or mixed network targets are blocked.")
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=8, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Never resolve the hostname again after policy validation (DNS rebinding).
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def inspect_page(url):
    url = public_url(url)
    origin = urlsplit(url).hostname
    for _ in range(4):
        parts = urlsplit(url)
        if parts.hostname != origin:
            raise ValueError("Cross-origin redirects require a new explicit inspection.")
        connection = PinnedHTTPS(parts.hostname, public_addresses(parts.hostname)[0])
        try:
            path = parts.path + (("?" + parts.query) if parts.query else "")
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/html,text/plain",
                    "Accept-Encoding": "identity",
                    "User-Agent": "INARA-ReadOnly/1",
                },
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = public_url(urljoin(url, response.getheader("Location", "")))
                continue
            if response.status != 200:
                raise ValueError("The server did not return a readable page.")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if (
                content_type not in ("text/html", "text/plain")
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
            ):
                raise ValueError("Only uncompressed HTML and plain text are supported.")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Page exceeds the inspection size limit.")
            text = raw.decode("utf-8", errors="replace")
            if content_type == "text/plain":
                return BrowserReport(
                    url=url, title=parts.hostname, text=text[:12000], links=[]
                ).model_dump()
            parser = PageText(url)
            parser.feed(text)
            return parser.report()
        finally:
            connection.close()
    raise ValueError("Redirect limit exceeded.")
