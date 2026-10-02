"""Explicit current-user credentials for the fixed official search endpoint only.

The native application owns sign-in and refresh. Nothing here writes credentials,
copies them into an extension home, refreshes tokens, or retries a request.
"""
import hashlib
import os
from pathlib import Path

from .model_registry import RouterError

CONTRACT = 'official_current_user_search_v1'


def checked_home(value):
    from operator_native_models import checked_path
    try:
        expected = Path(os.environ['USERPROFILE']) / '.codex'
        path = checked_path(value, directory=True)
        if path != expected:
            raise ValueError()
        return path
    except (KeyError, OSError, ValueError):
        raise RouterError('native_search_home_invalid') from None


def identity(value):
    return None if value is None else hashlib.sha256(str(checked_home(value)).encode()).hexdigest()


def load_headers(home):
    from operator_native_models import decode, read
    try:
        value = decode(read(checked_home(home) / 'auth.json'))
        if not isinstance(value, dict) or value.get('auth_mode') != 'chatgpt':
            raise ValueError()
        tokens = value.get('tokens')
        if not isinstance(tokens, dict):
            raise ValueError()
        access, account = tokens.get('access_token'), tokens.get('account_id')
        for token, maximum in ((access, 65536), (account, 512)):
            if (not isinstance(token, str) or not 0 < len(token) <= maximum
                    or not all(33 <= ord(c) <= 126 for c in token)):
                raise ValueError()
        return {'Authorization': 'Bearer ' + access, 'ChatGPT-Account-Id': account}
    except (OSError, ValueError, KeyError):
        raise RouterError('native_search_sign_in_unavailable') from None
