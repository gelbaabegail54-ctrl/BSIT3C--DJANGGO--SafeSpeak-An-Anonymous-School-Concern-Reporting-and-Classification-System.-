"""Test-only compatibility patches for running Django 5.0 on Python 3.14.

Django 5.0's ``BaseContext.__copy__`` relies on ``copy(super())`` returning an
object that accepts a ``dicts`` attribute. Python 3.14 changed that behaviour,
so the Django test client crashes while copying the context of any rendered
template (which breaks every test that renders a page).

This module restores the intended shallow-copy behaviour for test runs only.
Remove it once Django is upgraded to a release that supports Python 3.14.
"""

from django.template.context import BaseContext


def _compat_copy(self):
    duplicate = self.__class__.__new__(self.__class__)
    duplicate.__dict__ = self.__dict__.copy()
    duplicate.dicts = self.dicts[:]
    return duplicate


if not getattr(BaseContext, '_safespeak_python314_copy_patch', False):
    BaseContext.__copy__ = _compat_copy
    BaseContext._safespeak_python314_copy_patch = True
