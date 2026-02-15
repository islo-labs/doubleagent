"""Dual-target contract validation helpers.

When ``DOUBLEAGENT_DUAL_TARGET=1`` is set, test functions decorated with
``@readonly`` are run against both the fake *and* the real API.  The
helper compares responses and reports diffs.

Usage in a contract test::

    from doubleagent_sdk.dual_target import (
        is_dual_target_enabled,
        compare_responses,
        readonly,
    )

    @readonly
    def test_list_repos(github_client):
        repos = github_client.get_user().get_repos()
        assert len(list(repos)) > 0

When ``DOUBLEAGENT_DUAL_TARGET=1`` the test runner should supply both a
"fake" and a "real" client.  The ``compare_responses`` helper diffs two
JSON-like objects, ignoring volatile fields like timestamps and IDs.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable

# Marker for read-only tests that can safely run against a real API
_READONLY_ATTR = "_doubleagent_readonly"

VOLATILE_FIELDS = {
    "id", "node_id", "created_at", "updated_at", "pushed_at",
    "etag", "last_modified", "url", "html_url", "git_url",
    "ssh_url", "clone_url", "svn_url", "avatar_url",
    "gravatar_id", "followers_url", "following_url",
    "gists_url", "starred_url", "subscriptions_url",
    "organizations_url", "repos_url", "events_url",
    "received_events_url", "hooks_url", "issues_url",
    "members_url", "public_members_url",
}


def is_dual_target_enabled() -> bool:
    """Return True if dual-target validation mode is active."""
    return os.environ.get("DOUBLEAGENT_DUAL_TARGET", "") == "1"


def readonly(fn: Callable) -> Callable:
    """Mark a test as read-only (safe to run against the real API)."""
    setattr(fn, _READONLY_ATTR, True)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    setattr(wrapper, _READONLY_ATTR, True)
    return wrapper


def is_readonly(fn: Callable) -> bool:
    """Check whether a test function is marked as read-only."""
    return getattr(fn, _READONLY_ATTR, False)


def compare_responses(
    fake_response: Any,
    real_response: Any,
    *,
    ignore_fields: set[str] | None = None,
    path: str = "$",
) -> list[str]:
    """Compare two JSON-like responses, returning a list of diff descriptions.

    Ignores fields in ``VOLATILE_FIELDS`` plus any additional
    ``ignore_fields``.  Returns an empty list if the responses match.
    """
    skip = VOLATILE_FIELDS | (ignore_fields or set())
    diffs: list[str] = []
    _compare(fake_response, real_response, skip, path, diffs)
    return diffs


def _compare(
    fake: Any, real: Any, skip: set[str], path: str, diffs: list[str]
) -> None:
    if isinstance(fake, dict) and isinstance(real, dict):
        all_keys = set(fake.keys()) | set(real.keys())
        for key in sorted(all_keys):
            if key in skip:
                continue
            child_path = f"{path}.{key}"
            if key not in fake:
                diffs.append(f"{child_path}: missing in fake (real has {type(real[key]).__name__})")
            elif key not in real:
                diffs.append(f"{child_path}: extra in fake (not in real response)")
            else:
                _compare(fake[key], real[key], skip, child_path, diffs)
    elif isinstance(fake, list) and isinstance(real, list):
        if len(fake) != len(real):
            diffs.append(f"{path}: list length differs (fake={len(fake)}, real={len(real)})")
        for i, (f_item, r_item) in enumerate(zip(fake, real)):
            _compare(f_item, r_item, skip, f"{path}[{i}]", diffs)
    elif type(fake) != type(real):
        diffs.append(f"{path}: type differs (fake={type(fake).__name__}, real={type(real).__name__})")
    elif fake != real:
        # Truncate long values
        f_str = str(fake)[:80]
        r_str = str(real)[:80]
        diffs.append(f"{path}: value differs (fake={f_str!r}, real={r_str!r})")
