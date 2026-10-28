const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../pryx_comfyui_higgsfield/web/js/settings.js'), 'utf8');

function loadCredentialSettings(context, autoSession = true) {
    const start = source.indexOf('const SETTINGS_ROUTE =');
    const end = source.indexOf('\nasync function refreshCatalog()', start);
    assert.notEqual(start, -1);
    assert.notEqual(end, -1);
    if (autoSession) {
        const fetch = context.fetch;
        context.fetch = (url, options) => url.endsWith('/session')
            ? Promise.resolve({ ok: true, json: async () => ({ token: 'test-session-token' }) })
            : fetch(url, options);
    }
    vm.createContext(context);
    vm.runInContext(source.slice(start, end), context);
    return context;
}

test('combined Higgsfield key splits at the first colon and trims pasted whitespace', () => {
    const context = loadCredentialSettings({
        document: { querySelectorAll: () => [] },
        fetch: async () => ({ ok: true, json: async () => ({}) }),
    });
    const parsed = context.splitCombinedApiKey('  key-id : secret:with:colon  ');

    assert.equal(parsed.key_id, 'key-id');
    assert.equal(parsed.secret, 'secret:with:colon');
});

test('combined Higgsfield key rejects missing ID or secret without echoing input', () => {
    const context = loadCredentialSettings({
        document: { querySelectorAll: () => [] },
        fetch: async () => ({ ok: true, json: async () => ({}) }),
    });

    for (const value of ['', 'id-only', ':secret', 'id:']) {
        assert.throws(
            () => context.splitCombinedApiKey(value),
            { message: 'Paste the full Higgsfield API key in KEY_ID:SECRET format.' },
        );
    }
});

test('saving a combined key stores both parts, clears and closes the dialog, and refreshes status', async () => {
    const requests = [];
    const statusElement = { textContent: 'Checking...' };
    const form = {
        elements: {
            api_key: { value: 'test-id:test-secret', focus() {} },
            status: { textContent: '' },
        },
        addEventListener() {},
    };
    const buttons = new Map();
    const document = {
        activeElement: null,
        body: {
            appendChild(element) {
                element.parent = this;
                this.overlay = element;
            },
        },
        createElement(tag) {
            return {
                tag,
                style: {},
                listeners: {},
                attributes: {},
                setAttribute(name, value) { this.attributes[name] = value; },
                addEventListener(name, callback) { this.listeners[name] = callback; },
                appendChild(element) { this.children = [...(this.children || []), element]; },
                querySelector(selector) {
                    if (selector === 'form') return form;
                    return buttons.get(selector);
                },
                remove() { this.removed = true; },
            };
        },
        getElementById() { return null; },
        querySelectorAll(selector) {
            if (selector === '[data-pryx-comfyui-higgsfield-credential-status]') return [statusElement];
            return [];
        },
        querySelector() { return null; },
        addEventListener() {},
        removeEventListener() {},
    };
    for (const action of ['close', 'cancel', 'validate', 'save']) {
        buttons.set(`[data-action="${action}"]`, {
            addEventListener(name, callback) { this[name] = callback; },
        });
    }

    const context = loadCredentialSettings({
        document,
        app: {},
        console,
        fetch: async (url, options) => {
            requests.push({ url, options });
            return {
                ok: true,
                json: async () => ({ configured: true, source: 'local', key_id: 'te…id' }),
            };
        },
    });

    context.openCredentialDialog();
    const overlay = document.body.overlay;
    await buttons.get('[data-action="save"]').click();

    assert.equal(requests.length, 1);
    assert.equal(requests[0].options.method, 'PUT');
    assert.equal(requests[0].options.headers['X-PRYX-Higgsfield-Token'], 'test-session-token');
    assert.deepEqual(JSON.parse(requests[0].options.body), {
        key_id: 'test-id',
        secret: 'test-secret',
    });
    assert.equal(form.elements.api_key.value, '');
    assert.equal(overlay.removed, true);
    assert.equal(statusElement.textContent, 'Configured (te…id)');
});

test('a server restart renews the session and retries only the rejected request', async () => {
    const requests = [];
    let sessions = 0;
    const context = loadCredentialSettings({
        fetch: async (url, options) => {
            requests.push({ url, options });
            if (url.endsWith('/session')) {
                return { ok: true, json: async () => ({ token: `session-${++sessions}` }) };
            }
            if (options.headers['X-PRYX-Higgsfield-Token'] === 'session-1') {
                return { ok: false, status: 403, json: async () => ({ code: 'session_token_invalid' }) };
            }
            return { ok: true, json: async () => ({ configured: true }) };
        },
    }, false);
    const result = await context.requestJson('/pryx-comfyui-higgsfield/settings', { method: 'PUT', body: '{}' });
    assert.equal(result.configured, true);
    assert.equal(requests.length, 4);
    assert.equal(sessions, 2);
    assert.equal(requests[0].options.method, 'POST');
    assert.equal(requests[0].options.body, '{}');
    assert.equal(requests[0].options.cache, 'no-store');
    assert.equal(requests[3].options.headers['X-PRYX-Higgsfield-Token'], 'session-2');
});

test('generic failures and network failures never replay settings writes', async () => {
    for (const networkFailure of [false, true]) {
        let writes = 0;
        const context = loadCredentialSettings({ fetch: async () => {
            writes++;
            if (networkFailure) throw new Error('Network failure');
            return { ok: false, status: 403, json: async () => ({ error: 'Forbidden' }) };
        } });
        await assert.rejects(context.requestJson('/settings', { method: 'PUT', body: '{}' }));
        assert.equal(writes, 1);
    }
});

test('an expired session retries at most once and bootstrap failures can recover', async () => {
    let calls = 0;
    const context = loadCredentialSettings({ fetch: async () => {
        calls++;
        return { ok: false, status: 403, json: async () => ({ code: 'session_token_invalid' }) };
    } });
    await assert.rejects(context.requestJson('/settings', { method: 'DELETE' }));
    assert.equal(calls, 2);

    let attempts = 0;
    const recovering = loadCredentialSettings({ fetch: async (url) => {
        if (url.endsWith('/session')) {
            if (++attempts === 1) throw new Error('Offline');
            return { ok: true, json: async () => ({ token: 'new-session' }) };
        }
        return { ok: true, json: async () => ({ configured: true }) };
    } }, false);
    await assert.rejects(recovering.requestJson('/settings'));
    assert.equal((await recovering.requestJson('/settings')).configured, true);
    assert.equal(attempts, 2);
});

test('model updates show restart status and notify only once per pending version', () => {
    const status = { textContent: '' };
    const notifications = [];
    const context = loadCredentialSettings({
        document: { querySelectorAll: () => [status] },
        app: { ui: { dialog: { show: (message) => notifications.push(message) } } },
        console,
    });
    const update = { message: 'Current models loaded from the API.', restart_required: true, catalog_version: '2030-01-01.1' };
    context.handleCatalogStatus({ detail: update });
    context.handleCatalogStatus({ detail: update });
    assert.equal(notifications.length, 1);
    assert.match(status.textContent, /Restart ComfyUI/);
    context.handleCatalogStatus({ detail: { ...update, catalog_version: '2030-01-01.2' } });
    assert.equal(notifications.length, 2);
    context.handleCatalogStatus({ detail: { message: 'API discovery failed. Keeping the last working models.', restart_required: false } });
    assert.match(status.textContent, /Keeping the last working models/);
    assert.equal(notifications.length, 2);
});

test('a manual model check with no changed schema does not ask for a restart', async () => {
    const status = { textContent: '' };
    const notifications = [];
    const context = loadCredentialSettings({
        document: { querySelectorAll: () => [status] },
        app: { ui: { dialog: { show: (message) => notifications.push(message) } } },
        fetch: async () => ({ ok: true, json: async () => ({ message: 'Models are current.', restart_required: false }) }),
    });
    vm.runInContext(source.slice(source.indexOf('async function refreshCatalog()'), source.indexOf('\nfunction handleProgress')), context);
    await context.refreshCatalog();
    assert.equal(status.textContent, 'Models are current.');
    assert.match(notifications[0], /No restart is needed/);
});
