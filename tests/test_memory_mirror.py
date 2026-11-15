"""S6.4: the read-only Markdown mirror of "What JARVIS knows" (docs/MEMORY.md)."""

import os
import stat

import pytest

from services.memory_facts import (
    MIRROR_HEADER,
    FactStore,
    MarkdownMirror,
    mirror_markdown,
    mirror_path,
)
from services.storage import Database

START = 1_790_000_000.0


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


class Timers:
    """A fake ``threading.Timer``: records each timer; ``fire()`` runs the live one."""

    def __init__(self):
        self.made = []

    def __call__(self, delay, callback):
        timers = self

        class Timer:
            daemon = True

            def __init__(self):
                self.delay, self.callback = delay, callback
                self.started = self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        timer = Timer()
        timers.made.append(timer)
        return timer

    def live(self):
        return [timer for timer in self.made if timer.started and not timer.cancelled]

    def fire(self):
        (timer,) = self.live()
        timer.cancelled = True
        timer.callback()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return FactStore(Database(tmp_path / "private"), clock=clock)


@pytest.fixture
def timers():
    return Timers()


@pytest.fixture
def mirror(tmp_path, store, timers):
    mirror = MarkdownMirror(tmp_path / "data" / "memory" / "MEMORY.md", store.list, timer=timers)
    store.on_change = mirror.changed
    return mirror


def add(store, clock, kind, subject, text, **extra):
    clock.now += 60
    return store.add(kind, subject, text, **extra)


def test_markdown_groups_like_the_page_pinned_first(store, clock):
    add(store, clock, "episode", "Langkawi", "Went to Langkawi in March.")
    add(store, clock, "preference", "Tea", "Likes teh tarik less sweet.")
    add(store, clock, "profile", "Name", "Is called Hiro.")
    add(store, clock, "preference", "Music", "Plays lo-fi while working.", pinned=True)
    add(store, clock, "preference", "Coffee", "Avoids coffee after 4 pm.")
    add(store, clock, "person", "Aina", "Aina is the landlord.")
    text = mirror_markdown(store.list())
    assert text.splitlines()[:3] == ["# What JARVIS knows", "", MIRROR_HEADER]
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## About you", "## Preferences", "## People", "## Moments"]
    preferences = text.split("## Preferences\n\n")[1].split("\n\n")[0].splitlines()
    assert preferences == [
        "- **Music** — Plays lo-fi while working.",  # pinned first
        "- **Coffee** — Avoids coffee after 4 pm.",  # then newest first
        "- **Tea** — Likes teh tarik less sweet.",
    ]
    assert "Places" not in text and "Routines" not in text
    assert text.endswith("\n")


def test_markdown_neutralises_markup_and_shows_an_empty_store():
    fact = {"kind": "place", "subject": "Office *HQ*", "text": "Line one\nline_two `x`",
            "pinned": False}
    assert "- **Office \\*HQ\\*** — Line one line\\_two \\`x\\`" in mirror_markdown([fact])
    empty = mirror_markdown([])
    assert MIRROR_HEADER in empty and "Nothing remembered yet." in empty and "## " not in empty


def test_changes_are_debounced_into_one_write(store, clock, mirror, timers):
    add(store, clock, "preference", "Tea", "Likes teh tarik.")
    fact = add(store, clock, "place", "Office", "Works in Bangsar.")
    store.update(fact["id"], pinned=True)
    assert len(timers.made) == 3 and len(timers.live()) == 1  # earlier ones cancelled
    assert timers.live()[0].delay == 1.0 and timers.live()[0].daemon is False
    assert not mirror.path.exists()  # nothing written before the delay
    timers.fire()
    text = mirror.path.read_text(encoding="utf-8")
    assert "- **Tea** — Likes teh tarik." in text and "- **Office** — Works in Bangsar." in text
    # Left writable, so deleting the data folder (profile cleanup) never fails on it.
    assert os.stat(mirror.path).st_mode & stat.S_IWRITE
    assert not mirror.path.with_name("MEMORY.md.tmp").exists()


def test_every_kind_of_change_reaches_the_mirror(store, clock, mirror, timers):
    fact = add(store, clock, "preference", "Tea", "Likes teh tarik.")
    timers.fire()
    newer = store.supersede(fact["id"], "Likes teh o ais.")
    timers.fire()
    text = mirror.path.read_text(encoding="utf-8")
    assert "teh o ais" in text and "teh tarik" not in text  # superseded facts are left out
    assert store.forget(newer["id"])
    timers.fire()
    assert "Nothing remembered yet." in mirror.path.read_text(encoding="utf-8")
    assert not store.forget(newer["id"])  # nothing deleted: no new rewrite
    assert timers.live() == []


def test_no_write_when_nothing_changed(store, clock, mirror):
    add(store, clock, "routine", "Gym", "Goes to the gym on Thursdays.")
    assert mirror.flush() is True
    before = os.stat(mirror.path).st_mtime_ns
    assert mirror.flush() is False
    assert os.stat(mirror.path).st_mtime_ns == before
    store.set_paused(True)  # the pause switch is not part of the mirror
    assert mirror.flush() is False


def test_close_writes_a_pending_change_then_stops(store, clock, mirror, timers):
    add(store, clock, "profile", "Name", "Is called Hiro.")
    mirror.close()
    assert "Is called Hiro." in mirror.path.read_text(encoding="utf-8")
    assert timers.live() == []
    add(store, clock, "profile", "Town", "Lives in Petaling Jaya.")
    assert timers.live() == []


def test_a_failed_write_is_logged_without_fact_text(tmp_path, caplog):
    blocker = tmp_path / "memory"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    fact = {"kind": "profile", "subject": "Secretish", "text": "Very private words",
            "pinned": False}
    mirror = MarkdownMirror(blocker / "MEMORY.md", lambda: [fact])
    assert mirror.flush() is False
    assert "Memory mirror could not be written" in caplog.text
    assert "private words" not in caplog.text and "Secretish" not in caplog.text


def test_the_service_mirrors_into_the_data_folder(application_factory):
    app = application_factory()
    mirror = app.facts.mirror
    assert mirror.path == mirror_path(app.database)
    assert mirror.path == app.database.directory / "memory" / "MEMORY.md"
    assert app.facts.store.on_change == mirror.changed
    app.facts.store.add("preference", "Tea", "Likes teh tarik.")
    mirror.close()
    assert "- **Tea** — Likes teh tarik." in mirror.path.read_text(encoding="utf-8")
