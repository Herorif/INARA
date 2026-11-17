"""Skills (S5.2, docs/SKILLS.md): folders of instructions JARVIS can load when a request fits.

A skill is the open Agent Skills layout: ``<slug>/SKILL.md`` with YAML front matter (``name``
and ``description``) and Markdown instructions, plus an optional ``scripts/`` folder. Two
places hold them:

- ``<user data>\\skills\\`` (the owner's, beside the core's database), and
- ``<repo>\\skills\\`` (shipped with JARVIS, "built-in").

An owner skill overrides a shipped one with the same slug. Folders are re-read only when
something in them changes (a cheap stat of each ``SKILL.md`` before each turn).

The system prompt carries a stable index after the persona, one line per skill sorted by
slug (``skill_index``): it is a pure function of the skills' slugs and descriptions, so the
cached prefix changes only when the set of skills (or a description) changes. The brain's
``load_skill`` (never asks) returns a skill's instructions; ``teach_skill`` ("Teach JARVIS",
always asks, outward) shows the exact ``SKILL.md`` on the approval card and saves it on
approve. Nothing in a skill folder is ever executed here: ``scripts/`` is listed, never run;
scripts run only through JARVIS's existing approved local-action paths.

There is no YAML library in the core: the front matter is a strict subset (one
``key: value`` per line; plain, "double-quoted" or 'single-quoted' scalars; no nesting).
Logs never carry a skill's name, description or instructions.
"""

import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from services.log import get_logger
from services.tools import ServiceError, ToolSpec

logger = get_logger(__name__)

SHIPPED_ROOT = Path(__file__).resolve().parents[2] / "skills"
FOLDER = "skills"  # under the user data folder
SKILL_FILE = "SKILL.md"
SCRIPTS_DIR = "scripts"
SLUG = re.compile(r"[a-z0-9-]{1,48}")
SLUG_PATTERN = r"^[a-z0-9-]{1,48}$"
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 300
BODY_LIMIT = 20_000
FILE_LIMIT = 256 * 1024  # bytes read from one SKILL.md before decoding
FRONT_MATTER_LINES = 50
MAX_SKILLS = 100  # per location, by slug order; the rest are skipped
MAX_SCRIPTS_LISTED = 50
SOURCES = {"owner": "yours", "shipped": "built-in"}
INDEX_HEADER = (
    "Skills you can load with load_skill (load one when a request fits it, then follow its "
    "instructions):"
)
SCRIPTS_NOTE = (
    "These files are listed only. JARVIS never runs a skill's scripts by itself; run one only "
    "through a tool that asks the owner, and only if the owner wants it."
)

_KEY_LINE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]+(.*))?")
_DOUBLE = re.compile(r'"((?:[^"\\]|\\.)*)"(?:[ \t]+#.*)?')
_SINGLE = re.compile(r"'((?:[^']|'')*)'(?:[ \t]+#.*)?")
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r"}
_PLAIN_FIRST = set("[]{}|>&*!%@`,?\"'")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class SkillError(ValueError):
    """A SKILL.md that does not meet the format or the limits (message in plain words)."""


@dataclass(frozen=True)
class Skill:
    slug: str
    name: str
    description: str
    body: str
    source: str  # "owner" or "shipped"
    path: Path  # the skill's folder
    scripts: tuple = ()  # relative file names under scripts/, listed and never run

    def entry(self):
        return {
            "slug": self.slug, "name": self.name, "description": self.description,
            "source": SOURCES[self.source], "path": str(self.path),
            "scripts": list(self.scripts),
        }


# --- the format ------------------------------------------------------------------------------
def _unescape(text):
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        code = text[index + 1:index + 2]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            index += 2
        elif code == "u" and re.fullmatch(r"[0-9A-Fa-f]{4}", text[index + 2:index + 6]):
            out.append(chr(int(text[index + 2:index + 6], 16)))
            index += 6
        else:
            raise SkillError("A quoted value has an escape SKILL.md doesn't support.")
    return "".join(out)


def _scalar(raw):
    value = (raw or "").strip()
    if not value or value.startswith("#"):
        return ""
    if value[0] == '"':
        match = _DOUBLE.fullmatch(value)
        if not match:
            raise SkillError("A double-quoted value isn't closed properly.")
        return _unescape(match.group(1))
    if value[0] == "'":
        match = _SINGLE.fullmatch(value)
        if not match:
            raise SkillError("A single-quoted value isn't closed properly.")
        return match.group(1).replace("''", "'")
    value = re.split(r"[ \t]#", value, maxsplit=1)[0].rstrip()
    if value[0] in _PLAIN_FIRST or value.startswith("- ") or value == "-":
        raise SkillError("Put quotes around a value that starts with a symbol.")
    if ": " in value or value.endswith(":"):
        raise SkillError("Put quotes around a value that has a colon in it.")
    return value


def _line_text(value, label, limit):
    if not isinstance(value, str) or not value.strip():
        raise SkillError(f"The skill needs a {label}.")
    value = value.strip()
    if "\n" in value or "\r" in value or _CONTROL.search(value) or "\t" in value:
        raise SkillError(f"The {label} must be one line of plain text.")
    if len(value) > limit:
        raise SkillError(f"The {label} is longer than {limit} characters.")
    return value


def clean_body(body):
    if not isinstance(body, str):
        raise SkillError("The skill needs instructions.")
    body = body.replace("\r\n", "\n").strip()
    if not body:
        raise SkillError("The skill needs instructions.")
    if "\r" in body or _CONTROL.search(body):
        raise SkillError("The instructions must be plain text.")
    if len(body) > BODY_LIMIT:
        raise SkillError(f"The instructions are longer than {BODY_LIMIT:,} characters.")
    return body


def parse_skill(text):
    """``(fields, body)`` from a SKILL.md's text; ``fields`` has a checked ``name`` and
    ``description`` (other keys are kept as read). Raises SkillError."""
    if not isinstance(text, str):
        raise SkillError("SKILL.md must be text.")
    text = text.removeprefix("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        raise SkillError("SKILL.md must start with a --- line and its front matter.")
    end = next(
        (index for index in range(1, min(len(lines), FRONT_MATTER_LINES + 2))
         if lines[index].rstrip() == "---"),
        None,
    )
    if end is None:
        raise SkillError("The front matter has no closing --- line.")
    fields = {}
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise SkillError("The front matter can't have nested or multi-line values.")
        match = _KEY_LINE.fullmatch(line)
        if not match:
            raise SkillError("Each front matter line must be key: value.")
        key = match.group(1)
        if key in fields:
            raise SkillError(f"The front matter has {key} twice.")
        fields[key] = _scalar(match.group(2))
    fields["name"] = _line_text(fields.get("name"), "name", NAME_LIMIT)
    fields["description"] = _line_text(fields.get("description"), "description",
                                       DESCRIPTION_LIMIT)
    return fields, clean_body("\n".join(lines[end + 1:]))


def _quoted(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_skill(name, description, body):
    """The SKILL.md text ``teach_skill`` writes (and the approval card shows)."""
    name = _line_text(name, "name", NAME_LIMIT)
    description = _line_text(description, "description", DESCRIPTION_LIMIT)
    body = clean_body(body)
    return (f"---\nname: {_quoted(name)}\ndescription: {_quoted(description)}\n---\n\n"
            f"{body}\n")


def slugify(name):
    """'Plan my day' -> 'plan-my-day' (letters and digits, hyphens between; at most 48)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug[:48].rstrip("-")


def skill_index(skills):
    """The system prompt's skill lines (sorted by slug); "" with no skills. Pure: the same
    skills always give the same bytes."""
    if not skills:
        return ""
    ordered = sorted(skills.values() if isinstance(skills, dict) else skills,
                     key=lambda skill: skill.slug)
    return "\n".join([INDEX_HEADER, *(f"- {skill.slug}: {skill.description}"
                                      for skill in ordered)])


def _is_link(path):
    path = Path(path)
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def _list_scripts(folder):
    """Relative names of the files under ``scripts/`` (never read, never run)."""
    root = folder / SCRIPTS_DIR
    if not root.is_dir() or _is_link(root):
        return ()
    names = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(item for item in dirs if not _is_link(Path(current) / item))
        for item in sorted(files):
            names.append((Path(current) / item).relative_to(root).as_posix())
            if len(names) >= MAX_SCRIPTS_LISTED:
                return tuple(names)
    return tuple(names)


def read_skill(folder, source):
    """One skill folder -> Skill. Raises SkillError (OSError for an unreadable file)."""
    folder = Path(folder)
    slug = folder.name
    if not SLUG.fullmatch(slug):
        raise SkillError("The folder name must be 1-48 lowercase letters, digits or hyphens.")
    file = folder / SKILL_FILE
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise SkillError("SKILL.md must be a plain file.")
    if info.st_size > FILE_LIMIT:
        raise SkillError("SKILL.md is too large.")
    with open(file, "rb") as handle:
        data = handle.read(FILE_LIMIT + 1)
    if len(data) > FILE_LIMIT:
        raise SkillError("SKILL.md is too large.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError("SKILL.md must be UTF-8 text.") from exc
    fields, body = parse_skill(text)
    return Skill(slug, fields["name"], fields["description"], body, source, folder,
                 _list_scripts(folder))


# --- brain tool arguments ----------------------------------------------------------------------
class SkillLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=NAME_LIMIT,
                            description="The skill's name from the skills list, e.g. plan-my-day.")


class SkillTeach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=NAME_LIMIT,
                            description="A short name, e.g. Plan my day. Its slug "
                            "(plan-my-day) names the skill.")
    description: StrictStr = Field(min_length=1, max_length=DESCRIPTION_LIMIT,
                                   description="One line: what the skill does and when to use it.")
    instructions: StrictStr = Field(min_length=1, max_length=BODY_LIMIT,
                                    description="The steps in Markdown, written as instructions "
                                    "to JARVIS.")


LOAD_DESCRIPTION = (
    "Load one of JARVIS's skills by name (from the skills list in your instructions) and get "
    "its instructions. Load it when a request fits the skill's description, then follow it."
)
TEACH_DESCRIPTION = (
    "Teach JARVIS a skill: when the owner says to remember how to do something, write it up "
    "as a skill (a short name, a one-line description of when to use it, and the steps as "
    "Markdown instructions). The owner sees the exact file on screen and approves every save. "
    "A built-in skill's name can't be reused."
)


class SkillLibrary:
    """The owner's and the shipped skills, the index and the two brain tools. Owned by the
    composition root; reads only, until the owner approves a teach_skill or deletes one."""

    def __init__(self, app=None, *, owner_root=None, shipped_root=SHIPPED_ROOT):
        self.app = app
        if owner_root is None and app is not None:
            directory = getattr(getattr(app, "database", None), "directory", None)
            owner_root = None if directory is None else Path(directory) / FOLDER
        self.owner_root = None if owner_root is None else Path(owner_root)
        self.shipped_root = None if shipped_root is None else Path(shipped_root)
        self.signature = None
        self.loaded = {}  # slug -> Skill, owner over shipped
        self.shipped = {}  # slug -> Skill (built-in only)
        self.skipped = []  # (source, reason) of folders that were not loaded
        self.index = ""
        if app is not None:
            app.dispatcher.register(ToolSpec(
                "load_skill", LOAD_DESCRIPTION, SkillLoad, self._load_tool,
                execution_timeout=10,
            ))
            app.dispatcher.register(ToolSpec(
                "teach_skill", TEACH_DESCRIPTION, SkillTeach, self._teach_tool,
                execution_timeout=10, always_ask=True, review=self._teach_review,
                outward=True,
            ))

    # --- reading -----------------------------------------------------------------------------
    def _roots(self):
        return (("shipped", self.shipped_root), ("owner", self.owner_root))

    @staticmethod
    def _candidates(root):
        """Skill folders in ``root`` by name (no links), at most MAX_SKILLS."""
        if root is None:
            return []
        try:
            entries = sorted(os.scandir(root), key=lambda entry: entry.name)
        except OSError:
            return []
        folders = []
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False) or _is_link(entry.path):
                    continue
            except OSError:
                continue
            folders.append(Path(entry.path))
            if len(folders) >= MAX_SKILLS:
                break
        return folders

    def _stamp(self):
        """What a reload depends on: each candidate's SKILL.md and scripts/ stat."""
        stamp = []
        for source, root in self._roots():
            for folder in self._candidates(root):
                parts = [source, folder.name]
                for path in (folder / SKILL_FILE, folder / SCRIPTS_DIR):
                    try:
                        info = path.lstat()
                        parts += [info.st_mtime_ns, info.st_size]
                    except OSError:
                        parts += [None, None]
                stamp.append(tuple(parts))
        return tuple(stamp)

    def refresh(self, force=False):
        """Re-read the folders when anything in them changed; returns ``{slug: Skill}``."""
        stamp = self._stamp()
        if not force and stamp == self.signature:
            return self.loaded
        shipped, owner, skipped = {}, {}, []
        for source, root in self._roots():
            target = shipped if source == "shipped" else owner
            for folder in self._candidates(root):
                if not (folder / SKILL_FILE).exists():
                    continue
                try:
                    target[folder.name] = read_skill(folder, source)
                except (SkillError, OSError) as exc:
                    skipped.append((source, str(exc) if isinstance(exc, SkillError)
                                    else type(exc).__name__))
                    logger.warning("A %s skill was skipped: %s", SOURCES[source],
                                   skipped[-1][1])
        self.shipped = shipped
        self.loaded = {**shipped, **owner}
        self.skipped = skipped
        self.index = skill_index(self.loaded)
        self.signature = stamp
        return self.loaded

    def index_text(self):
        """The system prompt's skill index ("" with no skills). Never raises."""
        try:
            self.refresh()
        except Exception as exc:
            logger.warning("Skills could not be read (%s)", type(exc).__name__)
        return self.index

    def find(self, name):
        """A skill by slug, by the slug of ``name``, or by its name (case ignored)."""
        skills = self.refresh()
        if not isinstance(name, str):
            return None
        key = name.strip()
        if key in skills:
            return skills[key]
        if slugify(key) in skills:
            return skills[slugify(key)]
        lowered = key.casefold()
        return next((skill for skill in skills.values() if skill.name.casefold() == lowered),
                    None)

    def list(self):
        return [skill.entry() for _, skill in sorted(self.refresh().items())]

    # --- owner changes -----------------------------------------------------------------------
    def draft(self, name, description, instructions):
        """``(slug, SKILL.md text, existing owner skill or None)`` for a skill the owner may
        save. Raises ServiceError: invalid, a built-in slug, or no user data folder."""
        if self.owner_root is None:
            raise ServiceError("skills_unavailable", "Skills can't be saved on this PC.")
        slug = slugify(name)
        if not slug:
            raise ServiceError("invalid_arguments", "Give the skill a name with letters or digits.")
        try:
            text = render_skill(name, description, instructions)
        except SkillError as exc:
            raise ServiceError("invalid_arguments", str(exc)) from exc
        skills = self.refresh()
        if slug in self.shipped:
            raise ServiceError(
                "skill_built_in",
                f"{slug} is a built-in skill. Pick another name for this one.",
            )
        existing = skills.get(slug)
        return slug, text, existing if existing and existing.source == "owner" else None

    def save(self, name, description, instructions):
        """Write ``<user data>\\skills\\<slug>\\SKILL.md`` (atomically); returns the Skill."""
        slug, text, existing = self.draft(name, description, instructions)
        folder = self.owner_root / slug
        if _is_link(folder) or (folder.exists() and not folder.is_dir()):
            raise ServiceError("skill_unsafe", "That skill's folder isn't a plain folder.")
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / (SKILL_FILE + ".partial")
        partial.write_bytes(text.encode("utf-8"))
        os.replace(partial, folder / SKILL_FILE)
        logger.info("Skill saved (replaced=%s)", existing is not None)
        self.refresh(force=True)
        return self.loaded[slug], existing is not None

    def delete(self, slug):
        """Delete one owner skill's folder. Built-in skills can't be deleted."""
        skills = self.refresh()
        skill = skills.get(slug)
        if skill is None or skill.source != "owner":
            if slug in self.shipped:
                raise ServiceError("skill_built_in", "Built-in skills can't be deleted.")
            raise ServiceError("skill_not_found", "That skill is gone.")
        folder = self.owner_root / slug
        if _is_link(folder) or folder.resolve().parent != self.owner_root.resolve():
            raise ServiceError("skill_unsafe", "That skill's folder isn't a plain folder.")
        shutil.rmtree(folder)
        logger.info("Skill deleted")
        self.refresh(force=True)
        return slug

    # --- brain tools -------------------------------------------------------------------------
    def _authorize(self, context):
        self.app.authorize_owner(context)

    async def _load_tool(self, args, context):
        self._authorize(context)
        skill = self.find(args.name)
        if skill is None:
            raise ServiceError("skill_not_found",
                               "There's no skill by that name. Check the skills list.")
        result = {"skill": skill.slug, "name": skill.name, "instructions": skill.body}
        if skill.scripts:
            result.update(scripts=list(skill.scripts), scripts_note=SCRIPTS_NOTE)
        return result

    def _teach_review(self, args, context):
        self._authorize(context)
        slug, text, existing = self.draft(args.name, args.description, args.instructions)
        return {
            "slug": slug,
            "skill_md": text,
            "replaces": f"Replaces your existing skill {slug}." if existing else None,
        }

    async def _teach_tool(self, args, context):
        self._authorize(context)
        skill, replaced = self.save(args.name, args.description, args.instructions)
        return {"saved": True, "skill": skill.slug, "name": skill.name, "replaced": replaced}
