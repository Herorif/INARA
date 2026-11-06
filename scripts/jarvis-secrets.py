"""Manage JARVIS's provider API keys in the profile's DPAPI-protected store.

Keys are read from standard input only (never the command line) and are never
printed. Output is one JSON object on stdout.

  jarvis-secrets.py [--data-dir DIR | --installation-root ROOT [--slot SLOT]] COMMAND
    status                     configured/source/last-four hint for every key
    set NAME [--verify]        read the key from stdin and store it
                               (--verify tests it first; a rejected key is not saved)
    test NAME [--stdin]        test the saved key, or a candidate read from stdin
    clear NAME                 delete the saved key

Data directory: --data-dir, else --installation-root (the selected version's
profile, ROOT/data/<slot>/database, as the launcher passes JARVIS_DATA_DIR), else
JARVIS_DATA_DIR, else %LOCALAPPDATA%/JARVIS/data-v1 (developer default).

Exit codes: 0 ok, 2 invalid input, 3 test failed, 4 storage error.
"""

import argparse
from contextlib import contextmanager
import getpass
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

EXIT_OK, EXIT_INPUT, EXIT_TEST, EXIT_STORAGE = 0, 2, 3, 4
# Anything that looks like a provider key on argv is refused without echoing it.
KEY_SHAPED = re.compile(r"(sk-ant-|AIza|AQ\.)[A-Za-z0-9_\-]{8,}")


class InputError(Exception):
    pass


class StorageFailure(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse would echo unrecognized arguments, which could be a pasted key.
        safe = "Invalid arguments." if "unrecognized" in message else message
        emit({"ok": False, "code": "invalid_arguments", "message": safe + " Keys are read from standard input only."})
        raise SystemExit(EXIT_INPUT)


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def read_secret():
    if sys.stdin is None:
        raise InputError("Pipe the key on standard input.")
    if sys.stdin.isatty():
        raw = getpass.getpass("Key (input hidden): ")
    else:
        data = sys.stdin.buffer.read(4097)
        if len(data) > 4096:
            raise InputError("Input is too long for an API key.")
        try:
            raw = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputError("Input is not valid text.") from exc
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise InputError("Provide exactly one key on standard input.")
    return lines[0]


@contextmanager
def installation_data(root, slot=None):
    """The data directory the launcher passes as JARVIS_DATA_DIR for this version.

    The installation's manager lock is held for the whole command, so Setup
    removal/recovery cannot run concurrently (a running JARVIS also holds it).
    """
    spec = importlib.util.spec_from_file_location(
        "jarvis_secrets_install", ROOT / "scripts/desktop-install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        service = module.Installation(Path(root), authenticated=True)
        lock = service.locked()
        state = lock.__enter__()
    except ValueError as exc:
        raise StorageFailure(str(exc)) from exc
    try:
        chosen = slot or state["current"]
        if chosen is None:
            raise StorageFailure("No version is selected in this installation yet.")
        if chosen not in state["slots"]:
            raise StorageFailure("That version is not installed here.")
        try:
            directory = service.data(state, chosen) / "database"
        except ValueError as exc:
            raise StorageFailure(str(exc)) from exc
        yield directory
    finally:
        lock.__exit__(None, None, None)


@contextmanager
def data_directory(args):
    if args.data_dir:
        yield Path(args.data_dir).expanduser().resolve()
    elif args.installation_root:
        with installation_data(args.installation_root, args.slot) as directory:
            yield directory
    else:
        from services.storage import user_data_directory

        yield user_data_directory()


@contextmanager
def open_store(args):
    from services.secrets import SecretStore
    from services.storage import Database, StorageError

    with data_directory(args) as directory:
        try:
            store = SecretStore(Database(directory))
        except (StorageError, OSError, sqlite3.Error) as exc:
            raise StorageFailure("Protected storage could not be opened.") from exc
        yield store


def run(args):
    from services.secrets import REGISTRY

    if args.command != "status" and args.name not in REGISTRY:
        raise InputError("Unknown key name. Use one of: " + ", ".join(REGISTRY) + ".")
    value = read_secret() if args.command == "set" or args.stdin else None
    with open_store(args) as store:
        return execute(args, store, value)


def execute(args, store, value):
    from services.secrets import check_message, spec_for
    from services.tools import ServiceError

    if args.command == "status":
        return EXIT_OK, {"ok": True, "secrets": store.statuses()}
    spec = spec_for(args.name)
    if args.command == "clear":
        return EXIT_OK, {"ok": True, "secret": store.clear(args.name)}
    if args.command == "test" and value is None:
        try:
            status = store.test(args.name)
        except ServiceError as exc:
            return EXIT_INPUT, {"ok": False, "code": exc.code, "message": str(exc)}
        code = status["last_check"]["code"]
        return (EXIT_OK if code == "ok" else EXIT_TEST), {
            "ok": code == "ok", "code": code, "message": check_message(args.name, code),
            "secret": status,
        }
    try:
        value = store.validate(args.name, value)
    except ServiceError:
        return EXIT_INPUT, {"ok": False, "code": "invalid_format", "message": spec.format_message}
    if args.command == "test":
        check = store.check_value(args.name, value)
        return (EXIT_OK if check["ok"] else EXIT_TEST), {
            "ok": check["ok"], "code": check["code"],
            "message": check_message(args.name, check["code"]), "saved": False,
        }
    check = store.check_value(args.name, value) if args.verify else None
    if check and check["code"] == "invalid_key":
        return EXIT_TEST, {
            "ok": False, "code": "invalid_key", "saved": False,
            "message": check_message(args.name, "invalid_key") + " It was not saved.",
        }
    status = store.set(args.name, value, check)
    if check is None:
        message = "Key saved."
    elif check["ok"]:
        message = "Key saved and verified."
    else:
        message = "Key saved, but not verified. " + check_message(args.name, check["code"])
    return EXIT_OK, {
        "ok": True, "code": check["code"] if check else "saved", "message": message,
        "saved": True, "secret": status,
    }


def parser():
    root = Parser(prog="jarvis-secrets.py", description="Manage JARVIS provider API keys.")
    where = root.add_mutually_exclusive_group()
    where.add_argument("--data-dir", help="Profile database directory (JARVIS_DATA_DIR).")
    where.add_argument("--installation-root", help="Managed installation folder.")
    root.add_argument("--slot", help="Installed version (defaults to the selected one).")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("status")
    setter = commands.add_parser("set")
    setter.add_argument("name")
    setter.add_argument("--verify", action="store_true")
    tester = commands.add_parser("test")
    tester.add_argument("name")
    tester.add_argument("--stdin", action="store_true", help="Test a candidate key from stdin.")
    commands.add_parser("clear").add_argument("name")
    root.set_defaults(stdin=False, verify=False)
    return root


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(KEY_SHAPED.search(item) for item in argv):
        emit({"ok": False, "code": "key_on_command_line",
              "message": "Never pass a key on the command line. Pipe it on standard input."})
        return EXIT_INPUT
    args = parser().parse_args(argv)
    if args.slot and not args.installation_root:
        emit({"ok": False, "code": "invalid_arguments", "message": "--slot needs --installation-root."})
        return EXIT_INPUT
    try:
        code, result = run(args)
    except InputError as exc:
        code, result = EXIT_INPUT, {"ok": False, "code": "invalid_input", "message": str(exc)}
    except StorageFailure as exc:
        code, result = EXIT_STORAGE, {"ok": False, "code": "storage_error", "message": str(exc)}
    except Exception as exc:
        from services.storage import StorageError

        # Never print a traceback: it is the one place a value could leak.
        print(f"jarvis-secrets: {type(exc).__name__}", file=sys.stderr)
        storage = isinstance(exc, (StorageError, OSError, sqlite3.Error))
        code, result = EXIT_STORAGE, {
            "ok": False,
            "code": "storage_error" if storage else "unexpected",
            "message": "Protected storage could not be used."
            if storage
            else "The request could not be completed.",
        }
    emit(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
