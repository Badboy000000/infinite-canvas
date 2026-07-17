import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MESSAGING = (ROOT / "static/js/shared/messaging/index.js").as_uri()
MESSAGING_BOOTSTRAP = (ROOT / "static/js/shared/messaging/bootstrap.js").as_uri()
STORAGE = (ROOT / "static/js/shared/storage/index.js").as_uri()


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_bus_deduplicates_and_filters_only_its_own_client_id():
    result = run_node(
        f"""
        import {{ createMessageBus }} from {json.dumps(MESSAGING)};
        const sent = [];
        function fakeBridge(name) {{
          let receive;
          return {{
            name,
            start(handler) {{ receive = handler; }},
            send(message) {{ sent.push({{ name, message }}); }},
            inject(message) {{ receive(message); }},
          }};
        }}
        const broadcast = fakeBridge('broadcastChannel');
        const iframe = fakeBridge('iframeMessage');
        const bus = createMessageBus({{ localClientId: 'canvas_classic', bridges: [broadcast, iframe] }});
        let deliveries = 0;
        bus.on('canvas_updated', () => deliveries++);
        const emitted = bus.emit({{ type: 'canvas_updated', client_id: 'canvas_other' }});
        broadcast.inject(emitted);
        iframe.inject(emitted);
        iframe.inject({{ type: 'canvas_updated', client_id: 'canvas_classic', message_id: 'own' }});
        iframe.inject({{ type: 'canvas_updated', client_id: 'canvas_smart', message_id: 'other' }});
        console.log(JSON.stringify({{
          deliveries,
          sentCount: sent.length,
          sameMessageId: sent[0].message.message_id === sent[1].message.message_id,
        }}));
        """
    )
    assert result == {"deliveries": 2, "sentCount": 2, "sameMessageId": True}


def test_bus_deduplicates_legacy_messages_without_ids_and_iframe_parent_top_once():
    result = run_node(
        f"""
        import {{ createMessageBus, createIframeMessageBridge }} from {json.dumps(MESSAGING)};
        function fakeBridge(name) {{
          let receive;
          return {{
            name,
            start(handler) {{ receive = handler; }},
            send() {{}},
            inject(message) {{ receive(message); }},
          }};
        }}
        const broadcast = fakeBridge('broadcastChannel');
        const iframe = fakeBridge('iframeMessage');
        const bus = createMessageBus({{ bridges: [broadcast, iframe], legacyDedupeWindowMs: 500 }});
        let deliveries = 0;
        bus.on('providers-changed', () => deliveries++);
        const legacy = {{ type: 'providers-changed', updated_at: 42 }};
        broadcast.inject({{ ...legacy }});
        iframe.inject({{ ...legacy }});

        let listener;
        const sent = [];
        const parentAndTop = {{ postMessage(message, origin) {{ sent.push({{ message, origin }}); }} }};
        const fakeWindow = {{
          location: {{ origin: 'http://127.0.0.1:3000' }},
          parent: parentAndTop,
          top: parentAndTop,
          addEventListener(_type, handler) {{ listener = handler; }},
          removeEventListener() {{}},
        }};
        const iframeBridge = createIframeMessageBridge({{ windowRef: fakeWindow }});
        iframeBridge.start(() => {{}});
        iframeBridge.send(legacy);
        console.log(JSON.stringify({{ deliveries, sentCount: sent.length }}));
        """
    )
    assert result == {"deliveries": 1, "sentCount": 1}


def test_iframe_bridge_rejects_foreign_origin_and_uses_same_origin_target():
    result = run_node(
        f"""
        import {{ createIframeMessageBridge }} from {json.dumps(MESSAGING)};
        let listener;
        const sent = [];
        const target = {{ postMessage(message, origin) {{ sent.push({{ message, origin }}); }} }};
        const fakeWindow = {{
          location: {{ origin: 'http://127.0.0.1:3000' }},
          parent: target,
          top: target,
          addEventListener(type, handler) {{ if (type === 'message') listener = handler; }},
          removeEventListener() {{}},
        }};
        const accepted = [];
        const bridge = createIframeMessageBridge({{ windowRef: fakeWindow }});
        bridge.start(message => accepted.push(message.type));
        listener({{ origin: 'https://foreign.example', data: {{ type: 'providers-changed' }} }});
        listener({{ origin: 'http://127.0.0.1:3000', data: {{ type: 'providers-changed' }} }});
        bridge.send({{ type: 'workflows-changed' }});
        console.log(JSON.stringify({{ accepted, sent }}));
        """
    )
    assert result["accepted"] == ["providers-changed"]
    assert len(result["sent"]) == 1
    assert result["sent"][0]["origin"] == "http://127.0.0.1:3000"


def test_broadcast_websocket_and_storage_bridges_send_and_receive():
    result = run_node(
        f"""
        import {{
          createBroadcastChannelBridge,
          createStorageEventBridge,
          createWebSocketBridge,
        }} from {json.dumps(MESSAGING)};
        class FakeChannel {{
          constructor(name) {{ this.name = name; this.listeners = []; FakeChannel.instance = this; }}
          addEventListener(_type, handler) {{ this.listeners.push(handler); }}
          postMessage(message) {{ this.sent = message; }}
          close() {{ this.closed = true; }}
        }}
        const broadcastReceived = [];
        const broadcast = createBroadcastChannelBridge({{ BroadcastChannelImpl: FakeChannel }});
        broadcast.start(message => broadcastReceived.push(message.type));
        FakeChannel.instance.listeners[0]({{ data: {{ type: 'providers-changed' }} }});
        broadcast.send({{ type: 'workflows-changed' }});

        const socketListeners = [];
        const socket = {{
          readyState: 1,
          addEventListener(_type, handler) {{ socketListeners.push(handler); }},
          removeEventListener() {{}},
          send(value) {{ this.sent = value; }},
        }};
        const websocketReceived = [];
        const websocket = createWebSocketBridge({{ socket }});
        websocket.start(message => websocketReceived.push(message.type));
        socketListeners[0]({{ data: JSON.stringify({{ type: 'canvas_updated' }}) }});
        websocket.send({{ type: 'pong' }});

        let storageListener;
        const stored = [];
        const storageWindow = {{
          addEventListener(_type, handler) {{ storageListener = handler; }},
          removeEventListener() {{}},
        }};
        const storage = {{ setItem(key, value) {{ stored.push([key, value]); }} }};
        const storageReceived = [];
        const storageBridge = createStorageEventBridge({{
          windowRef: storageWindow,
          storage,
          toMessage: event => event.key === 'smart_canvas_asset_inbox'
            ? {{ type: 'asset_library_updated' }} : null,
        }});
        storageBridge.start(message => storageReceived.push(message.type));
        storageListener({{ key: 'smart_canvas_asset_inbox' }});
        storageBridge.send({{
          type: 'asset_library_updated',
          storage_key: 'smart_canvas_asset_inbox',
          storage_value: '[]',
        }});
        console.log(JSON.stringify({{
          broadcastReceived,
          broadcastSent: FakeChannel.instance.sent.type,
          websocketReceived,
          websocketSent: JSON.parse(socket.sent).type,
          storageReceived,
          stored,
        }}));
        """
    )
    assert result == {
        "broadcastReceived": ["providers-changed"],
        "broadcastSent": "workflows-changed",
        "websocketReceived": ["canvas_updated"],
        "websocketSent": "pong",
        "storageReceived": ["asset_library_updated"],
        "stored": [["smart_canvas_asset_inbox", "[]"]],
    }


def test_studio_bus_composes_all_four_production_channels():
    result = run_node(
        f"""
        import {{ createStudioBus }} from {json.dumps(MESSAGING)};
        class FakeChannel {{
          constructor() {{ this.listeners = []; FakeChannel.instance = this; }}
          addEventListener(_type, handler) {{ this.listeners.push(handler); }}
          postMessage() {{}}
          close() {{}}
        }}
        const windowListeners = {{}};
        const fakeWindow = {{
          location: {{ origin: 'http://127.0.0.1:3000' }},
          parent: null,
          top: null,
          addEventListener(type, handler) {{ (windowListeners[type] ||= []).push(handler); }},
          removeEventListener() {{}},
        }};
        const socketListeners = [];
        const socket = {{
          addEventListener(type, handler) {{ if (type === 'message') socketListeners.push(handler); }},
          removeEventListener() {{}},
        }};
        const bus = createStudioBus({{
          windowRef: fakeWindow,
          BroadcastChannelImpl: FakeChannel,
          socket,
          storageEvent: {{
            windowRef: fakeWindow,
            toMessage: event => event.key === 'studio_theme'
              ? {{ type: 'studio-theme', theme: event.newValue }} : null,
          }},
        }});
        const received = [];
        bus.on('providers-changed', message => received.push(['broadcast', message.type]));
        bus.on('canvas_updated', message => received.push(['websocket', message.canvas_id]));
        bus.on('studio-theme', message => received.push(['storage', message.theme]));
        FakeChannel.instance.listeners[0]({{ data: {{ type: 'providers-changed' }} }});
        socketListeners[0]({{ data: JSON.stringify({{ type: 'canvas_updated', canvas_id: 'c1' }}) }});
        windowListeners.storage[0]({{ key: 'studio_theme', newValue: 'dark' }});
        console.log(JSON.stringify({{
          received,
          messageListeners: windowListeners.message.length,
          storageListeners: windowListeners.storage.length,
          socketListeners: socketListeners.length,
        }}));
        """
    )
    assert result == {
        "received": [
            ["broadcast", "providers-changed"],
            ["websocket", "c1"],
            ["storage", "dark"],
        ],
        "messageListeners": 1,
        "storageListeners": 1,
        "socketListeners": 1,
    }


def test_bootstrap_handoff_keeps_early_messages_and_reject_fallback_without_duplicates():
    result = run_node(
        f"""
        await import({json.dumps(MESSAGING_BOOTSTRAP)});
        const {{ createMessagingBootstrap }} = globalThis.StudioMessagingBootstrap;
        class FakeChannel {{
          static instances = [];
          constructor() {{ this.listeners = []; FakeChannel.instances.push(this); }}
          addEventListener(_type, handler) {{ this.listeners.push(handler); }}
          removeEventListener(_type, handler) {{ this.listeners = this.listeners.filter(item => item !== handler); }}
          postMessage(message) {{ this.sent = message; }}
          close() {{ this.closed = true; }}
          inject(message) {{ this.listeners.forEach(handler => handler({{ data: {{ ...message }} }})); }}
        }}
        function fakeWindow() {{
          const listeners = {{}};
          const parentAndTop = {{ sent: [], postMessage(message) {{ this.sent.push(message); }} }};
          return {{
            location: {{ origin: 'http://127.0.0.1:3000' }},
            parent: parentAndTop,
            top: parentAndTop,
            listeners,
            addEventListener(type, handler) {{ (listeners[type] ||= []).push(handler); }},
            removeEventListener(type, handler) {{
              listeners[type] = (listeners[type] || []).filter(item => item !== handler);
            }},
            inject(type, event) {{ (listeners[type] || []).forEach(handler => handler(event)); }},
          }};
        }}

        let resolveModule;
        const pendingModule = new Promise(resolve => {{ resolveModule = resolve; }});
        const handoffWindow = fakeWindow();
        const handoff = createMessagingBootstrap({{
          loadModule: () => pendingModule,
          windowRef: handoffWindow,
          BroadcastChannelImpl: FakeChannel,
        }});
        let refreshes = 0;
        const connection = handoff.connect({{
          types: ['providers-changed'],
          onMessage: () => refreshes++,
        }});
        const early = {{ type: 'providers-changed', updated_at: 1 }};
        handoffWindow.inject('message', {{ origin: handoffWindow.location.origin, data: {{ ...early }} }});
        FakeChannel.instances[0].inject(early);
        connection.emit({{ type: 'workflows-changed' }});
        const fallbackTargetSends = handoffWindow.parent.sent.length;

        resolveModule(await import({json.dumps(MESSAGING)}));
        await connection.ready;
        const liveChannel = FakeChannel.instances.at(-1);
        const live = {{ type: 'providers-changed', updated_at: 2 }};
        liveChannel.inject(live);
        handoffWindow.inject('message', {{ origin: handoffWindow.location.origin, data: {{ ...live }} }});

        const rejectedWindow = fakeWindow();
        const rejected = createMessagingBootstrap({{
          loadModule: () => Promise.reject(new Error('offline import')),
          windowRef: rejectedWindow,
          BroadcastChannelImpl: FakeChannel,
        }});
        let rejectedDeliveries = 0;
        const rejectedConnection = rejected.connect({{
          types: ['providers-changed'],
          onMessage: () => rejectedDeliveries++,
        }});
        await rejectedConnection.ready;
        rejectedWindow.inject('message', {{
          origin: rejectedWindow.location.origin,
          data: {{ type: 'providers-changed' }},
        }});
        rejectedConnection.emit({{ type: 'providers-changed' }});
        console.log(JSON.stringify({{
          earlyRefreshes: refreshes,
          fallbackTargetSends,
          rejectedDeliveries,
          rejectedTargetSends: rejectedWindow.parent.sent.length,
          legacyMessageListenersAfterHandoff: handoffWindow.listeners.message.length,
        }}));
        """
    )
    assert result == {
        "earlyRefreshes": 2,
        "fallbackTargetSends": 1,
        "rejectedDeliveries": 1,
        "rejectedTargetSends": 1,
        "legacyMessageListenersAfterHandoff": 1,
    }


def test_message_types_and_legacy_storage_keys_are_frozen():
    result = run_node(
        f"""
        import {{ STUDIO_MESSAGE_TYPES }} from {json.dumps(MESSAGING)};
        import {{ LEGACY_STORAGE_KEYS, namespacedKey }} from {json.dumps(STORAGE)};
        console.log(JSON.stringify({{
          types: [...STUDIO_MESSAGE_TYPES].sort(),
          keys: [...LEGACY_STORAGE_KEYS].sort(),
          generated: namespacedKey('canvas', 'panel-state', 2),
        }}));
        """
    )
    assert result["types"] == sorted(
        [
            "canvas-focus",
            "studio-theme",
            "studio-ui-scale",
            "studio-ui-scale-pause",
            "studio-lang",
            "providers-changed",
            "workflows-changed",
            "comfy-instances-changed",
            "stats",
            "cloud_status",
            "canvas_updated",
            "asset_library_updated",
            "new_image",
            "pong",
        ]
    )
    assert len(result["keys"]) == 30
    assert len(set(result["keys"])) == 30
    assert "smart_canvas_asset_inbox" in result["keys"]
    assert "canvas_session_viewports_v1" in result["keys"]
    assert result["generated"] == "studio:canvas:panel-state:v2"


def test_message_payload_validation_is_type_specific_and_legacy_compatible():
    result = run_node(
        f"""
        import {{ isStudioMessage }} from {json.dumps(MESSAGING)};
        const cases = [
          {{ type: 'providers-changed' }},
          {{ type: 'providers-changed', updated_at: 123 }},
          {{ type: 'providers-changed', updated_at: 'yesterday' }},
          {{ type: 'studio-theme', theme: 'dark' }},
          {{ type: 'studio-theme', theme: 1 }},
          {{ type: 'studio-ui-scale', mode: 'auto', scale: 1.25 }},
          {{ type: 'studio-ui-scale', scale: 'large' }},
          {{ type: 'canvas_updated', canvas_id: 'canvas-1', updated_at: 99 }},
          {{ type: 'canvas_updated', canvas_id: 7 }},
          {{ type: 'stats', online_count: 2 }},
          {{ type: 'stats', online_count: 'two' }},
          {{ type: 'pong' }},
        ];
        console.log(JSON.stringify(cases.map(isStudioMessage)));
        """
    )
    assert result == [True, True, False, True, False, True, False, True, False, True, False, True]


def test_three_existing_client_id_generators_remain_distinct():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    canvas = (ROOT / "static/js/canvas.js").read_text(encoding="utf-8")
    smart = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

    assert 'const CID = localStorage.getItem("client_id") || generateUUID();' in index
    assert "const CLIENT_ID = 'canvas_' + Math.random().toString(36).slice(2);" in canvas
    assert "const smartClientId = `canvas_smart_${Math.random()" in smart
    assert "localClientId: CID" in index
    assert "localClientId: CLIENT_ID" in canvas
    assert "localClientId: smartClientId" in smart


def test_authorized_call_sites_use_the_bus_seam():
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    api_settings = (ROOT / "static/js/api-settings.js").read_text(encoding="utf-8")
    comfy = (ROOT / "static/js/comfyui-settings.js").read_text(encoding="utf-8")
    canvas = (ROOT / "static/js/canvas.js").read_text(encoding="utf-8")
    smart = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")

    assert "studioMessageConnection.emit(message)" in api_settings
    assert comfy.count("broadcastStudioApiChange('workflows-changed')") == 3
    assert "window.StudioMessaging.connect" in canvas
    assert "window.StudioMessaging.connect" in smart
    assert "studioMessageConnection.attachWebSocket(ws)" in index
    assert "smartCanvasMessageConnection.attachWebSocket(socket)" in smart
    assert "storageEvent:" in index
    assert "storageEvent:" in smart
    for source in (index, api_settings, comfy, canvas, smart):
        assert "import('/static/js/shared/messaging/index.js')" not in source


def test_messaging_bootstrap_cache_version_matches_all_esm_sources():
    messaging_dir = ROOT / "static/js/shared/messaging"
    digest = hashlib.sha256()
    for path in sorted(messaging_dir.rglob("*.js")):
        if path.name == "bootstrap.js":
            continue
        digest.update(path.relative_to(messaging_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    expected = digest.hexdigest()[:12]
    bootstrap = (messaging_dir / "bootstrap.js").read_text(encoding="utf-8")
    declared = re.search(r"MESSAGING_MODULE_VERSION = '([0-9a-f]{12})'", bootstrap)
    assert declared and declared.group(1) == expected


def test_all_bus_consumers_load_the_single_versioned_bootstrap():
    pages = [
        "index.html",
        "api-settings.html",
        "canvas.html",
        "comfyui-settings.html",
        "smart-canvas.html",
    ]
    versions = set()
    for page in pages:
        html = (ROOT / "static" / page).read_text(encoding="utf-8")
        matches = re.findall(r'/static/js/shared/messaging/bootstrap\.js\?v=([^"\']+)', html)
        assert len(matches) == 1, page
        versions.update(matches)
    assert len(versions) == 1
