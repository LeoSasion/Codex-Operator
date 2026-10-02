"""Explicit read-only native interruption evidence; no task loading or execution."""
import asyncio
from pathlib import Path
import stat
import time

from .app_server import AppServerSession
from .beeper_relay import discover_codex_executable, looks_like_thread_id


def checked_native_home(value):
    """Validate a saved home without reading configuration or task content."""
    try:
        if not isinstance(value, (str, Path)):
            raise ValueError
        home = Path(value)
        if not home.is_absolute() or '..' in home.parts:
            raise ValueError
        for path in [*reversed(home.parents), home]:
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise ValueError
        return home.resolve()
    except (OSError, ValueError, TypeError):
        raise ValueError('web_native_cancellation_home_invalid') from None


def read_interruption(identity, *, executable=None, session_factory=AppServerSession, codex_home=None):
    """Return True only for the exact completed interrupted turn, None if unknown."""
    if (not isinstance(identity, tuple) or len(identity) != 2
            or not all(isinstance(value, str) and looks_like_thread_id(value) for value in identity)):
        return None
    session = None
    try:
        home = checked_native_home(codex_home if codex_home is not None else Path.home() / '.codex')
        session = session_factory(executable or discover_codex_executable(), 2, codex_home=home)
        session.deadline = time.monotonic() + 2
        session.initialize()
        thread_id, turn_id = identity
        result = session.request('thread/read', {'threadId': thread_id, 'includeTurns': False})
        thread = result.get('thread') if isinstance(result, dict) else None
        if (not isinstance(thread, dict) or thread.get('id') != thread_id
                or thread.get('turns') not in (None, [])):
            return None
        result = session.request('thread/turns/list', {'threadId': thread_id,
            'limit': 20, 'sortDirection': 'desc', 'itemsView': 'notLoaded'})
        rows = result.get('data') if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) > 20 or any(
                not isinstance(row, dict) or row.get('items') not in (None, [])
                or row.get('itemsView') != 'notLoaded' for row in rows):
            return None
        matches = [row for row in rows if row.get('id') == turn_id]
        if len(matches) != 1:
            return None
        row = matches[0]
        if row.get('status') not in ('inProgress', 'completed', 'failed', 'interrupted'):
            return None
        ended = row.get('completedAt')
        return row['status'] == 'interrupted' and type(ended) is int and ended > 0
    except Exception:
        # Transport/version/metadata uncertainty never becomes cancellation.
        return None
    finally:
        if session is not None:
            session.close()


async def observe_interruption(identity, *, codex_home=None):
    # Keep bounded blocking I/O off the event loop. If the owning turn ends,
    # await the read-only child's cleanup instead of orphaning it or retrying.
    pending = asyncio.create_task(asyncio.to_thread(read_interruption, identity, codex_home=codex_home))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await pending
        raise
