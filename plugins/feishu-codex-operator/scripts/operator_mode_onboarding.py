"""Dated, local-only preference seed for a new isolated Desktop home.

This skips the ordinary project/role welcome flow. Authentication and feature
access are checked earlier by Desktop and are not changed by this preference.
Never copy another profile or rewrite a home that has already been opened.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from operator_native_models import checked_path, decode


CONTRACT = 'operator_desktop_welcome_preference_20261002_v1'
PREFERENCE = 'electron:onboarding-projectless-completed'
ASSET = 'webview/assets/app-initial-3916b423772b.js'
REVIEWED_VERSION = '26.928.3736.0'
# Filled from the exact read-only packaged asset review, not a remote download.
REVIEWED_SHA256 = '6adb799eee56bfddf78fe098aa4842b9ff42efae0cd223dee8fb5be7cb0ca6c4'


def asset_bytes(archive: Path, asset: str) -> bytes:
    checked_path(archive)
    with archive.open('rb') as stream:
        prefix = stream.read(16)
        if len(prefix) != 16:
            raise ValueError('mode_onboarding_archive_invalid')
        base = 8 + struct.unpack('<I', prefix[4:8])[0]
        size = struct.unpack('<I', prefix[12:16])[0]
        if not 0 < size <= 32 * 1024 * 1024 or base < size + 16:
            raise ValueError('mode_onboarding_archive_invalid')
        header = decode(stream.read(size))
        node = header
        for part in asset.split('/'):
            node = node['files'][part]
        length = node['size']
        offset = int(node['offset'])
        if node.get('unpacked') or type(length) is not int or not 0 < length <= 32 * 1024 * 1024 or offset < 0:
            raise ValueError('mode_onboarding_asset_invalid')
        stream.seek(base + offset)
        raw = stream.read(length)
        if len(raw) != length:
            raise ValueError('mode_onboarding_asset_invalid')
        return raw


def inspect_contract(package: dict) -> dict:
    # Unknown versions retain their own normal onboarding. No generic completed
    # marker, guessed private API, authentication bypass or UI clicking fallback.
    result = {'contract': CONTRACT, 'supported': False, 'preferences': {}}
    if package['version'] != REVIEWED_VERSION:
        return result
    archive = Path(package['executable']).parent / 'resources' / 'app.asar'
    raw = asset_bytes(archive, ASSET)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != REVIEWED_SHA256:
        return result
    result.update(supported=True, asset=ASSET, asset_sha256=actual,
                  preferences={PREFERENCE: True})
    return result


def initial_state(contract: dict) -> bytes | None:
    if contract.get('supported') is not True:
        return None
    if (contract.get('contract') != CONTRACT or contract.get('asset') != ASSET
            or contract.get('asset_sha256') != REVIEWED_SHA256
            or contract.get('preferences') != {PREFERENCE: True}):
        raise ValueError('mode_onboarding_contract_invalid')
    return (json.dumps({'electron-persisted-atom-state': {PREFERENCE: True}},
                       ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
