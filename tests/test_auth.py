"""Tests for StaticTokenVerifier."""
import pytest

from scrapling_fetch_mcp._auth import StaticTokenVerifier


class TestStaticTokenVerifier:
    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self):
        verifier = StaticTokenVerifier("s3cret")
        result = await verifier.verify_token("s3cret")
        assert result is not None
        assert result.token == "s3cret"
        assert result.client_id == "static-client"
        assert result.scopes == []

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        verifier = StaticTokenVerifier("s3cret")
        assert await verifier.verify_token("wrong") is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self):
        verifier = StaticTokenVerifier("s3cret")
        assert await verifier.verify_token("") is None
