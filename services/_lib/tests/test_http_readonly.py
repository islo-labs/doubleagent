"""Unit tests for ReadOnlyHttpClient safety guarantees."""

import pytest
from doubleagent_sdk.http_readonly import ReadOnlyHttpClient, ReadOnlyViolation


def test_check_url_blocks_private_ip():
    client = ReadOnlyHttpClient()
    with pytest.raises(ReadOnlyViolation, match="private"):
        client._check_url("http://192.168.1.1/api")


def test_check_url_blocks_loopback():
    client = ReadOnlyHttpClient()
    with pytest.raises(ReadOnlyViolation, match="private"):
        client._check_url("http://127.0.0.1/api")


def test_check_url_allows_public():
    client = ReadOnlyHttpClient()
    # Should not raise
    client._check_url("https://api.github.com/user")


def test_check_url_allowlist_enforced():
    client = ReadOnlyHttpClient(allowed_hosts={"api.github.com"})
    client._check_url("https://api.github.com/repos")

    with pytest.raises(ReadOnlyViolation, match="not in allowed_hosts"):
        client._check_url("https://evil.example.com/steal")


def test_allow_private_skips_check():
    client = ReadOnlyHttpClient(allow_private=True)
    # Should not raise for private IPs
    client._check_url("http://192.168.1.1/api")


def test_post_blocked():
    """POST must raise ReadOnlyViolation (tested synchronously via _request guard)."""
    import asyncio

    async def _test():
        client = ReadOnlyHttpClient()
        async with client:
            with pytest.raises(ReadOnlyViolation, match="not allowed"):
                await client._request("POST", "https://api.github.com/repos")

    asyncio.run(_test())


def test_put_blocked():
    import asyncio

    async def _test():
        client = ReadOnlyHttpClient()
        async with client:
            with pytest.raises(ReadOnlyViolation, match="not allowed"):
                await client._request("PUT", "https://api.github.com/repos/x")

    asyncio.run(_test())


def test_delete_blocked():
    import asyncio

    async def _test():
        client = ReadOnlyHttpClient()
        async with client:
            with pytest.raises(ReadOnlyViolation, match="not allowed"):
                await client._request("DELETE", "https://api.github.com/repos/x")

    asyncio.run(_test())
