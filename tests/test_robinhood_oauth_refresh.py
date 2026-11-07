"""Real pinned SDK auth flows against a closed, synthetic HTTP transport."""

import asyncio
import json
from urllib.parse import parse_qs

import httpx2
import pytest
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from app.execution.market_read_worker import PrivateOAuthStorage
from app.options.read_worker import ReadAuthorizationRequired, authorization_required
from app.robinhood.client import JsonOAuthStorage
from app.robinhood.oauth import RestartRefreshOAuthClientProvider


RESOURCE = "https://resource.example.invalid/mcp"
ISSUER = "https://issuer.example.invalid"
CALLBACK = "http://127.0.0.1:8765/callback"


async def credentials(tmp_path, *, refresh="saved-refresh", issuer=ISSUER):
    path = tmp_path / "oauth.json"
    path.write_text(json.dumps({"tokens": {}, "client_info": {}}))
    path.chmod(0o600)
    storage = JsonOAuthStorage(path)
    await storage.set_client_info(OAuthClientInformationFull(
        client_id="saved-client", issuer=issuer, redirect_uris=[CALLBACK],
        token_endpoint_auth_method="none",
    ))
    await storage.set_tokens(OAuthToken(
        access_token="expired-access", token_type="Bearer", refresh_token=refresh,
        expires_in=1, scope="read",
    ))
    return PrivateOAuthStorage(path)


class Server:
    def __init__(self, *, status=401, refresh_status=200, rotate=False,
                 issuer=ISSUER, bad_metadata=False, reject_new=False):
        self.status = status
        self.refresh_status = refresh_status
        self.rotate = rotate
        self.issuer = issuer
        self.bad_metadata = bad_metadata
        self.reject_new = reject_new
        self.calls = []
        self.refreshes = []
        self.registrations = 0

    def __call__(self, request):
        url = str(request.url)
        self.calls.append(url)
        if url == RESOURCE:
            assert request.method == "GET"
            if request.headers.get("authorization") == "Bearer renewed-access" and not self.reject_new:
                return httpx2.Response(200, json={"ok": True})
            challenge = 'Bearer resource_metadata="https://resource.example.invalid/metadata"'
            if self.status == 403:
                challenge += ', error="insufficient_scope", scope="extra"'
            return httpx2.Response(self.status, headers={"WWW-Authenticate": challenge})
        if url == "https://resource.example.invalid/metadata":
            return httpx2.Response(200, json={
                "resource": RESOURCE, "authorization_servers": [self.issuer],
                "scopes_supported": ["read"],
            })
        if url == self.issuer + "/.well-known/oauth-authorization-server":
            return httpx2.Response(200, json={
                "issuer": "https://wrong.example.invalid" if self.bad_metadata else self.issuer,
                "authorization_endpoint": self.issuer + "/authorize",
                "token_endpoint": self.issuer + "/tokens",
                "registration_endpoint": self.issuer + "/register",
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
            })
        if url == self.issuer + "/tokens":
            data = parse_qs(request.content.decode())
            assert data["grant_type"] == ["refresh_token"]
            assert data["client_id"] == ["saved-client"]
            self.refreshes.append(data["refresh_token"][0])
            if self.refresh_status != 200:
                return httpx2.Response(self.refresh_status, json={"error": "invalid_grant"})
            body = {"access_token": "renewed-access", "token_type": "Bearer", "expires_in": 3600}
            if self.rotate:
                body["refresh_token"] = "rotated-refresh"
            return httpx2.Response(200, json=body)
        if url == self.issuer + "/register":
            self.registrations += 1
            return httpx2.Response(201, json={"client_id": "new-client", "redirect_uris": [CALLBACK]})
        raise AssertionError("Unexpected network route in closed OAuth fixture")


def provider(cls, storage):
    return cls(server_url=RESOURCE, storage=storage,
               client_metadata=OAuthClientMetadata(redirect_uris=[CALLBACK]),
               redirect_handler=authorization_required, callback_handler=authorization_required)


async def get(auth, server):
    async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(server)) as client:
        return await client.get(RESOURCE)


@pytest.mark.anyio
async def test_pinned_sdk_reproduces_restart_401_login_without_refresh(tmp_path):
    storage = await credentials(tmp_path)
    before = storage.path.read_bytes()
    server = Server()
    with pytest.raises(ReadAuthorizationRequired):
        await get(provider(OAuthClientProvider, storage), server)
    assert not server.refreshes
    assert storage.path.read_bytes() == before


@pytest.mark.anyio
@pytest.mark.parametrize("rotate", [False, True])
async def test_restart_refresh_uses_discovered_endpoint_and_preserves_grant(tmp_path, rotate):
    storage = await credentials(tmp_path)
    server = Server(rotate=rotate)
    assert (await get(provider(RestartRefreshOAuthClientProvider, storage), server)).status_code == 200
    assert server.refreshes == ["saved-refresh"] and not server.registrations
    assert server.calls == [RESOURCE, "https://resource.example.invalid/metadata",
                            ISSUER + "/.well-known/oauth-authorization-server",
                            ISSUER + "/tokens", RESOURCE]
    saved = await storage.get_tokens()
    assert saved.refresh_token == ("rotated-refresh" if rotate else "saved-refresh")
    assert saved.scope == "read" and saved.access_token == "renewed-access"
    assert storage.path.stat().st_mode & 0o777 == 0o600
    # A new worker reuses the saved token without refresh or login.
    following = Server()
    assert (await get(provider(RestartRefreshOAuthClientProvider,
                              PrivateOAuthStorage(storage.path)), following)).status_code == 200
    assert following.calls == [RESOURCE]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 429, 503])
async def test_rejected_refresh_stays_headless_and_is_not_retried(tmp_path, status):
    storage = await credentials(tmp_path)
    before = storage.path.read_bytes()
    server = Server(refresh_status=status)
    with pytest.raises(ReadAuthorizationRequired):
        await get(provider(RestartRefreshOAuthClientProvider, storage), server)
    assert server.refreshes == ["saved-refresh"]
    assert server.calls.count(RESOURCE) == 1
    assert storage.path.read_bytes() == before


@pytest.mark.anyio
async def test_second_401_does_not_loop_or_reauthorize(tmp_path):
    server = Server(reject_new=True)
    assert (await get(provider(RestartRefreshOAuthClientProvider,
                              await credentials(tmp_path)), server)).status_code == 401
    assert server.refreshes == ["saved-refresh"] and server.calls.count(RESOURCE) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["missing_refresh", "scope_step_up", "issuer_change"])
async def test_auth_requirements_never_bypass_headless_login(tmp_path, fault):
    storage = await credentials(tmp_path, refresh=None if fault == "missing_refresh" else "saved-refresh")
    server = Server(status=403 if fault == "scope_step_up" else 401,
                    issuer="https://new.example.invalid" if fault == "issuer_change" else ISSUER)
    with pytest.raises(ReadAuthorizationRequired):
        await get(provider(RestartRefreshOAuthClientProvider, storage), server)
    assert not server.refreshes
    assert server.registrations == int(fault == "issuer_change")


@pytest.mark.anyio
async def test_wrong_metadata_issuer_fails_before_any_grant_is_sent(tmp_path):
    from mcp.client.auth.exceptions import OAuthFlowError
    server = Server(bad_metadata=True)
    with pytest.raises(OAuthFlowError):
        await get(provider(RestartRefreshOAuthClientProvider, await credentials(tmp_path)), server)
    assert not server.refreshes and not server.registrations


@pytest.mark.anyio
async def test_native_later_expiry_refresh_still_works(tmp_path):
    server = Server()
    auth = provider(RestartRefreshOAuthClientProvider, await credentials(tmp_path))
    assert (await get(auth, server)).status_code == 200
    auth.context.token_expiry_time = 1
    assert (await get(auth, server)).status_code == 200
    assert server.refreshes == ["saved-refresh", "saved-refresh"]
    assert server.calls.count(ISSUER + "/.well-known/oauth-authorization-server") == 1


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["malformed", "timeout", "cancel"])
async def test_refresh_transport_failures_do_not_write_or_hold_the_auth_lock(tmp_path, fault):
    storage = await credentials(tmp_path)
    before = storage.path.read_bytes()
    server = Server()
    reached = asyncio.Event()
    calls = []
    async def transport(request):
        if str(request.url) == ISSUER + "/tokens":
            calls.append(1)
            reached.set()
            if fault == "malformed":
                return httpx2.Response(200, json={"private": "not-a-token"})
            if fault == "timeout":
                raise httpx2.ReadTimeout("synthetic", request=request)
            await asyncio.Event().wait()
        return server(request)
    auth = provider(RestartRefreshOAuthClientProvider, storage)
    async def request():
        async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(transport)) as client:
            return await client.get(RESOURCE)
    task = asyncio.create_task(request())
    await asyncio.wait_for(reached.wait(), 2)
    if fault == "cancel":
        task.cancel()
    expected = {"malformed": ReadAuthorizationRequired, "timeout": httpx2.ReadTimeout,
                "cancel": asyncio.CancelledError}[fault]
    with pytest.raises(expected):
        await task
    # httpx closes its auth iterator on failure; the nested SDK lock must follow.
    assert not auth.context.lock.locked()
    assert calls == [1] and storage.path.read_bytes() == before


@pytest.mark.anyio
async def test_rejected_refresh_keeps_explicit_interactive_pkce_fallback(tmp_path):
    from mcp.client.auth import AuthorizationCodeResult
    server = Server(refresh_status=400)
    redirects = []
    async def redirect(url):
        redirects.append(parse_qs(url.split("?", 1)[1]))
    async def callback():
        return AuthorizationCodeResult(code="human-code", state=redirects[-1]["state"][0])
    def transport(request):
        if str(request.url) == ISSUER + "/tokens":
            fields = parse_qs(request.content.decode())
            if fields["grant_type"] == ["authorization_code"]:
                assert fields["code"] == ["human-code"] and fields["code_verifier"]
                return httpx2.Response(200, json={"access_token": "renewed-access",
                    "token_type": "Bearer", "refresh_token": "human-refresh", "expires_in": 3600})
        return server(request)
    storage = await credentials(tmp_path)
    auth = RestartRefreshOAuthClientProvider(server_url=RESOURCE, storage=storage,
        client_metadata=OAuthClientMetadata(redirect_uris=[CALLBACK]),
        redirect_handler=redirect, callback_handler=callback)
    assert (await get(auth, transport)).status_code == 200
    assert len(redirects) == 1 and redirects[0]["code_challenge_method"] == ["S256"]
    assert (await storage.get_tokens()).refresh_token == "human-refresh"
