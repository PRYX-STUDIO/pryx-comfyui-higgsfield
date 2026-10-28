"""Exercise the local request boundary without real credentials or paid calls."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pryx_comfyui_higgsfield.request_guard import (
    TOKEN_HEADER,
    RequestGuard,
    same_origin,
)


@pytest.mark.parametrize("headers,expected", [
    ({}, False),
    ({"Sec-Fetch-Site": "same-origin"}, True),
    ({"Sec-Fetch-Site": "cross-site"}, False),
    ({"Sec-Fetch-Site": "same-site"}, False),
    ({"Sec-Fetch-Site": "none"}, False),
    ({"Origin": "http://localhost:8188"}, True),
    ({"Origin": "null"}, False),
    ({"Origin": "https://localhost:8188"}, False),
    ({"Origin": "http://localhost:8189"}, False),
    ({"Origin": "http://attacker.example"}, False),
    ({"Origin": "http://localhost:8188@attacker.example"}, False),
    ({"Origin": "http://localhost:8188/path"}, False),
    ({"Origin": "http://localhost:bad"}, False),
    ({"Origin": "http://localhost:8188", "Sec-Fetch-Site": "cross-site"}, False),
    ({"Origin": "http://attacker.example", "Sec-Fetch-Site": "same-origin"}, False),
])
def test_origin_boundary(headers, expected):
    assert same_origin(SimpleNamespace(headers=headers, host="localhost:8188", scheme="http")) is expected


def test_default_ports_and_ipv6():
    for host, origin, scheme in [("localhost:80", "http://localhost", "http"),
                                 ("example.test", "https://example.test:443", "https"),
                                 ("[::1]:8188", "http://[::1]:8188", "http")]:
        assert same_origin(SimpleNamespace(headers={"Origin": origin}, host=host, scheme=scheme))


def test_guard_blocks_foreign_requests_even_with_permissive_cors():
    async def run():
        effects = []
        guard = RequestGuard()

        @web.middleware
        async def permissive_cors(request, handler):
            response = web.Response() if request.method == "OPTIONS" else await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "*"
            return response

        async def mutate(request):
            effects.append(request.method)
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[permissive_cors])
        app.router.add_post('/session', guard.session)
        for method in ["PUT", "DELETE", "POST", "GET"]:
            app.router.add_route(method, '/settings', guard.protect(mutate))
        async with TestClient(TestServer(app)) as client:
            for headers in [{}, {"Origin": "null"}, {"Origin": "https://attacker.example"},
                            {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}]:
                response = await client.post('/session', headers=headers)
                assert response.status == 403
                assert 'token' not in await response.json()

            headers = {"Sec-Fetch-Site": "same-origin"}
            session = await client.post('/session', headers=headers)
            assert session.headers['Cache-Control'] == 'no-store'
            token = (await session.json())['token']
            assert token != RequestGuard()._token
            for method in ["PUT", "DELETE", "POST", "GET"]:
                for extras in [{}, {TOKEN_HEADER: "wrong"}, {TOKEN_HEADER: "\u00e4"}]:
                    response = await client.request(method, '/settings', headers={**headers, **extras})
                    assert response.status == 403
                    assert (await response.json())['code'] == 'session_token_invalid'
                response = await client.request(method, '/settings', headers={
                    "Origin": "https://attacker.example", TOKEN_HEADER: token})
                assert response.status == 403
                assert not effects
            for method in ["PUT", "DELETE", "POST", "GET"]:
                response = await client.request(method, '/settings', headers={**headers, TOKEN_HEADER: token})
                assert response.status == 200
                assert response.headers['Cache-Control'] == 'no-store'
                assert token not in json.dumps(await response.json())
            assert effects == ["PUT", "DELETE", "POST", "GET"]
            # HTTP LAN browser GETs may carry neither Origin nor fetch metadata.
            response = await client.get('/settings', headers={TOKEN_HEADER: token})
            assert response.status == 200
    asyncio.run(run())


def test_every_registered_plugin_route_is_guarded_and_credentials_remain_usable(monkeypatch, tmp_path):
    """Hit the production route table, not just a stand-in protected handler."""
    import sys

    from pryx_comfyui_higgsfield import server
    from pryx_comfyui_higgsfield.credentials import CredentialStore

    app = web.Application()
    prompt = SimpleNamespace(routes=web.RouteTableDef(), app=app)
    store = CredentialStore(tmp_path / 'test-credentials.json')
    monkeypatch.setitem(sys.modules, 'server', SimpleNamespace(PromptServer=SimpleNamespace(instance=prompt)))
    monkeypatch.setattr(server, '_registered', False)
    monkeypatch.setattr(server, '_prompt_server', None)
    monkeypatch.setattr(server, 'credential_store', lambda: store)
    monkeypatch.setattr(server, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    server.register_routes()
    app.add_routes(prompt.routes)

    async def run():
        async with TestClient(TestServer(app)) as client:
            base = '/pryx-comfyui-higgsfield'
            session = await client.post(base + '/session', headers={'Origin': str(client.make_url('/')).rstrip('/')})
            token = (await session.json())['token']
            for route in prompt.routes:
                if route.path.endswith('/session'):
                    continue
                for headers in [{}, {'Origin': 'https://attacker.example', TOKEN_HEADER: token},
                                {'Sec-Fetch-Site': 'same-origin', TOKEN_HEADER: 'wrong'}]:
                    response = await client.request(route.method, route.path, headers=headers, json={})
                    assert response.status == 403, (route.method, route.path)
            assert not store.path.exists()
            headers = {'Sec-Fetch-Site': 'same-origin', TOKEN_HEADER: token}
            response = await client.put(base + '/settings', headers=headers,
                                        json={'key_id': 'fixture-id', 'secret': 'fixture-secret'})
            assert response.status == 200
            assert (await response.json())['configured'] is True
            assert store.load() == ('fixture-id', 'fixture-secret')
            response = await client.get(base + '/settings', headers=headers)
            body = await response.json()
            assert response.status == 200 and body['configured'] is True
            assert 'fixture-secret' not in json.dumps(body)
            response = await client.delete(base + '/settings', headers=headers)
            assert response.status == 200
            assert not store.path.exists()
    asyncio.run(run())
