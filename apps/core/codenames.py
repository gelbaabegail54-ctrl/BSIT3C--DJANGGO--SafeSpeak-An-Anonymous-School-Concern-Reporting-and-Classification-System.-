"""Deterministic code names for anonymous SafeSpeak posters."""

import hashlib

_ADJECTIVES = (
    'Amber',
    'Brave',
    'Calm',
    'Clever',
    'Crimson',
    'Gentle',
    'Golden',
    'Graceful',
    'Hidden',
    'Kind',
    'Lively',
    'Lucky',
    'Mellow',
    'Noble',
    'Quiet',
    'Radiant',
    'Silent',
    'Silver',
    'Steady',
    'Swift',
    'Violet',
    'Wandering',
    'Wise',
    'Witty',
)

_NOUNS = (
    'Badger',
    'Cedar',
    'Comet',
    'Dolphin',
    'Eagle',
    'Falcon',
    'Fern',
    'Fox',
    'Harbor',
    'Heron',
    'Kestrel',
    'Lantern',
    'Lynx',
    'Maple',
    'Meadow',
    'Otter',
    'Owl',
    'Panda',
    'Raven',
    'Sparrow',
    'Tiger',
    'Willow',
    'Wolf',
    'Wren',
)


def _codename(seed):
    """Build a stable, human-friendly code name from a seed value."""
    digest = hashlib.sha256(f'safespeak:{seed}'.encode('utf-8')).digest()
    adjective = _ADJECTIVES[digest[0] % len(_ADJECTIVES)]
    noun = _NOUNS[digest[1] % len(_NOUNS)]
    number = 100 + int.from_bytes(digest[2:4], 'big') % 900
    return f'{adjective} {noun} {number}'


def user_codename(user_id):
    """Return the code name a regular user posts under."""
    return _codename(f'user:{user_id}')


def report_codename(kind, report_id):
    """Return a code name for a report that is not linked to an account."""
    return _codename(f'{kind}:{report_id}')


def comment_codename(comment_id):
    """Return a code name for a comment whose author is no longer known."""
    return _codename(f'comment:{comment_id}')
