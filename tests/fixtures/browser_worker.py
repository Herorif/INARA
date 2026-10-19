"""QA-only synthetic fetch adapter through the real fixed worker bootstrap/output."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from workers import browser_worker
from services.browser_fetch import PageText


def fixture(url):
    parser = PageText(url)
    parser.feed("<title>Owned worker fixture</title><p>Network disabled</p>")
    return parser.report()


def offline(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
        raise RuntimeError("No network allowed in browser worker QA")


sys.addaudithook(offline)
browser_worker.inspect_page = fixture
browser_worker.main()
