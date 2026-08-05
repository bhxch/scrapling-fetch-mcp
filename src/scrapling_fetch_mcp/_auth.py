"""Static bearer-token verifier for the streamable-http transport.

Implements the mcp SDK :class:`~mcp.server.auth.provider.TokenVerifier`
protocol for the simple case of a single shared secret (no OAuth flow).
When ``SCRAPLING_AUTH_TOKEN`` is configured, clients must send
``Authorization: Bearer <token>`` matching it.
"""

from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    """Verify bearer tokens against a single configured secret.

    Structurally satisfies the SDK ``TokenVerifier`` protocol (duck-typed;
    the protocol is not subclassed so we stay decoupled from runtime checks).
    """

    def __init__(self, expected_token: str):
        self._expected = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token and token == self._expected:
            return AccessToken(
                token=token,
                client_id="static-client",
                scopes=[],
            )
        return None
