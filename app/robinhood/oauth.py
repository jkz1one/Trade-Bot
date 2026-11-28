"""Bounded restart refresh adapter for the pinned MCP 2.3.0 OAuth provider.

The SDK loads saved tokens without an absolute expiry. On a resource 401 it
discovers/validates the issuer, then requests interactive authorization even when
a refresh token remains. Try that existing grant once at the SDK's authorization
boundary. Keep its discovery, issuer binding, redirect policy, request transport,
scope step-up, persistence and interactive/headless handlers intact.
"""

from mcp.client.auth import OAuthClientProvider


class RestartRefreshOAuthClientProvider(OAuthClientProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._resource_status = None
        self._restart_refresh_attempted = False
        self._restart_refresh_pending = False
        self._restart_refresh_handled = False

    async def _perform_authorization(self):
        # Called by the SDK only after resource/issuer validation and credential
        # binding. Never send an old grant to a newly advertised issuer or use
        # refresh to satisfy a 403 scope escalation. One attempt per connection.
        if (self._resource_status == 401 and not self._restart_refresh_attempted
                and self.context.can_refresh_token()):
            self._restart_refresh_attempted = True
            self._restart_refresh_pending = True
            return await self._refresh_token()
        return await super()._perform_authorization()

    async def _handle_token_response(self, response):
        if self._restart_refresh_handled:
            self._restart_refresh_handled = False
            return
        await super()._handle_token_response(response)

    async def _auth_flow(self, request):
        flow = super()._auth_flow(request)
        try:
            outgoing = await anext(flow)
            while True:
                response = yield outgoing
                if outgoing is request:
                    self._resource_status = response.status_code
                if self._restart_refresh_pending:
                    self._restart_refresh_pending = False
                    # Native handler preserves omitted refresh_token/scope,
                    # rotates credentials atomically and validates the response.
                    if await self._handle_refresh_response(response):
                        self._restart_refresh_handled = True
                    else:
                        # Rejected grants retain the original login requirement.
                        # A headless worker raises ReadAuthorizationRequired here.
                        outgoing = await super()._perform_authorization()
                        response = yield outgoing
                outgoing = await flow.asend(response)
        except StopAsyncIteration:
            return
        finally:
            # Release the native auth lock on cancellation/transport failure too.
            await flow.aclose()
