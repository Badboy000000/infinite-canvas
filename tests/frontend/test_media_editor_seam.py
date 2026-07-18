"""Frontend PR-4: shared/media/MediaEditor + fileApi + legacyUrlResolver seam tests.

Uses `node --experimental-default-type=module` to run assertion scripts against
the native ES modules on disk. Follows the pattern established by
`test_shared_messaging_storage.py` (前端 PR-3).
"""
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

MEDIA_EDITOR = (ROOT / "static/js/shared/media/MediaEditor/index.js").as_uri()
GRID_JOIN = (ROOT / "static/js/shared/media/MediaEditor/grid-join.js").as_uri()
RESOLVER = (ROOT / "static/js/shared/media/legacyUrlResolver.js").as_uri()
FILE_API = (ROOT / "static/js/shared/api-client/domains/fileApi.js").as_uri()
ENDPOINTS = (ROOT / "static/js/shared/api-client/endpoints.js").as_uri()
BOOTSTRAP = ROOT / "static/js/shared/media/bootstrap.js"


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


def test_media_editor_exposes_five_modes_and_two_canvas_kinds():
    result = run_node(
        f"""
        import mod from {json.dumps(MEDIA_EDITOR)};
        console.log(JSON.stringify({{
          modes: mod.MODES,
          kinds: mod.CANVAS_KINDS,
          hasOpen: typeof mod.open === 'function',
          hasRegister: typeof mod.register === 'function',
          hasIsOpen: typeof mod.isOpen === 'function',
        }}));
        """
    )
    assert result["modes"] == ["crop", "mask", "inpaint", "grid-split", "grid-join"]
    assert sorted(result["kinds"]) == ["classic", "smart"]
    assert result["hasOpen"] is True
    assert result["hasRegister"] is True
    assert result["hasIsOpen"] is True


def test_media_editor_open_returns_promise_and_finally_releases_active_session():
    result = run_node(
        f"""
        import mod from {json.dumps(MEDIA_EDITOR)};
        const calls = [];
        mod.register('classic', {{
          openImageEditor: (nodeId, mode) => calls.push({{fn:'openImageEditor', nodeId, mode}}),
          setImageEditMode: (mode, touched) => calls.push({{fn:'setImageEditMode', mode, touched}}),
        }});
        const results = {{}};
        // 逐一开启 5 个 mode 的 promise，验证每次 finally 后 active=null
        for (const mode of ['crop','mask','inpaint','grid-split']) {{
          const p = mod.open({{canvasKind:'classic', mode, source:{{nodeId:'n1'}}}});
          const val = await p;
          results[mode] = {{ ok: val.ok, mode: val.mode, activeAfter: mod.isOpen() }};
        }}
        // grid-join classic 无 adapter 支持，返回失败
        let gjError = null;
        try {{
          await mod.open({{canvasKind:'classic', mode:'grid-join',
                          source:{{items:[{{url:'/a'}},{{url:'/b'}}]}}}});
        }} catch(e) {{ gjError = String(e.message).slice(0, 80); }}
        console.log(JSON.stringify({{ results, calls, gjError, activeFinal: mod.isOpen() }}));
        """
    )
    for mode in ["crop", "mask", "inpaint", "grid-split"]:
        assert result["results"][mode]["ok"] is True
        assert result["results"][mode]["mode"] == mode
        assert result["results"][mode]["activeAfter"] is False
    assert "grid-join" in result["gjError"]
    assert result["activeFinal"] is False
    # 4 mode × classic 每次至少一次 openImageEditor 调用
    fn_names = [c["fn"] for c in result["calls"]]
    assert fn_names.count("openImageEditor") == 4


def test_media_editor_smart_grid_join_returns_promise_and_releases_session():
    result = run_node(
        f"""
        import mod from {json.dumps(MEDIA_EDITOR)};
        const calls = [];
        mod.register('smart', {{
          openImageEditor: (nodeId, imageIndex) => calls.push({{fn:'openImageEditor', nodeId, imageIndex}}),
          setImageEditMode: (mode, touched) => calls.push({{fn:'setImageEditMode', mode, touched}}),
          setGridOperationMode: (m) => calls.push({{fn:'setGridOperationMode', m}}),
          openGridJoin: (src) => calls.push({{fn:'openGridJoin', groupId:src.groupId, itemCount:src.items.length}}),
        }});
        const source = {{
          items: [{{url:'/output/a.png', w:1024, h:768}}, {{url:'/output/b.png', w:1024, h:768}}],
          layout: {{rows:1, cols:2}},
          gap: 8,
          groupId: 'g1',
          nodeId: 'n1',
          imageIndex: 0,
        }};
        const val = await mod.open({{canvasKind:'smart', mode:'grid-join', source}});
        console.log(JSON.stringify({{
          ok: val.ok, mode: val.mode, kind: val.canvasKind, itemCount: val.itemCount,
          calls, activeFinal: mod.isOpen(),
        }}));
        """
    )
    assert result["ok"] is True
    assert result["mode"] == "grid-join"
    assert result["kind"] == "smart"
    assert result["itemCount"] == 2
    assert result["activeFinal"] is False
    # openGridJoin 必须被调，且 groupId/itemCount 完整穿透
    open_calls = [c for c in result["calls"] if c["fn"] == "openGridJoin"]
    assert len(open_calls) == 1
    assert open_calls[0]["groupId"] == "g1"
    assert open_calls[0]["itemCount"] == 2


def test_grid_join_source_field_snapshot():
    """Grid-join source 字段清单快照。改动即回归。"""
    result = run_node(
        f"""
        import {{ gridJoin, GRID_JOIN_SOURCE_FIELDS, GRID_JOIN_ITEM_FIELDS }} from {json.dumps(GRID_JOIN)};
        console.log(JSON.stringify({{
          sourceFields: GRID_JOIN_SOURCE_FIELDS,
          itemFields: GRID_JOIN_ITEM_FIELDS,
          hasOpen: typeof gridJoin.open === 'function',
        }}));
        """
    )
    # 字段列表冻结（PR-4 契约）
    assert result["sourceFields"] == [
        "items", "layout", "gap", "groupId", "nodeId", "imageIndex"
    ]
    assert result["itemFields"] == ["url", "w", "h"]
    assert result["hasOpen"] is True


def test_grid_join_rejects_insufficient_items_and_missing_url():
    result = run_node(
        f"""
        import mod from {json.dumps(MEDIA_EDITOR)};
        mod.register('smart', {{
          openImageEditor: () => {{}},
          openGridJoin: () => {{}},
        }});
        const errors = [];
        try {{ await mod.open({{canvasKind:'smart', mode:'grid-join', source:{{items:[{{url:'/a'}}]}}}}); }}
        catch(e) {{ errors.push('one-item:' + String(e.message).slice(0, 40)); }}
        try {{ await mod.open({{canvasKind:'smart', mode:'grid-join', source:{{items:[{{url:'/a'}},{{}}]}}}}); }}
        catch(e) {{ errors.push('missing-url:' + String(e.message).slice(0, 40)); }}
        console.log(JSON.stringify({{errors}}));
        """
    )
    assert len(result["errors"]) == 2
    assert "one-item" in result["errors"][0]
    assert "missing-url" in result["errors"][1]


def test_legacy_url_resolver_normalizes_output_and_assets_consistently():
    result = run_node(
        f"""
        import {{ resolveLegacyUrl, unwrapMediaPreviewUrl, buildMediaPreviewUrl, buildDownloadOutputUrl, isLocalMediaUrl }} from {json.dumps(RESOLVER)};
        const cases = {{
          output:    resolveLegacyUrl('/output/xxx.png'),
          assets:    resolveLegacyUrl('/assets/output/xxx.png'),
          view:      resolveLegacyUrl('/api/view?filename=x.png'),
          preview:   resolveLegacyUrl('/api/media-preview?w=512&url=%2Foutput%2Fxxx.png'),
          download:  resolveLegacyUrl('/api/download-output?url=%2Foutput%2Fxxx.png&name=xxx'),
          data:      resolveLegacyUrl('data:image/png;base64,AAA'),
          blob:      resolveLegacyUrl('blob:http://localhost/xxx'),
          http:      resolveLegacyUrl('https://cdn.example.com/x.png'),
          empty:     resolveLegacyUrl(''),
        }};
        const unwrap = {{
          preview:  unwrapMediaPreviewUrl('/api/media-preview?w=512&url=%2Foutput%2Fxxx.png'),
          download: unwrapMediaPreviewUrl('/api/download-output?url=%2Foutput%2Fxxx.png&name=xxx'),
          direct:   unwrapMediaPreviewUrl('/output/xxx.png'),
        }};
        console.log(JSON.stringify({{
          cases,
          unwrap,
          previewOutput: buildMediaPreviewUrl('/output/xxx.png', 512),
          previewAssets: buildMediaPreviewUrl('/assets/output/xxx.png', 512),
          downloadInline: buildDownloadOutputUrl('/output/xxx.png', 'xxx.png', {{inline:true}}),
          isLocalOutput: isLocalMediaUrl('/output/xxx.png'),
          isLocalAssets: isLocalMediaUrl('/assets/output/xxx.png'),
          isLocalHttp:   isLocalMediaUrl('https://cdn.example.com/x.png'),
        }}));
        """
    )
    assert result["cases"]["output"]["kind"] == "output"
    assert result["cases"]["assets"]["kind"] == "assets"
    assert result["cases"]["view"]["kind"] == "api-view"
    assert result["cases"]["preview"]["kind"] == "media-preview"
    assert result["cases"]["preview"]["resolvedUrl"] == "/output/xxx.png"
    assert result["cases"]["download"]["kind"] == "download-output"
    assert result["cases"]["download"]["resolvedUrl"] == "/output/xxx.png"
    assert result["cases"]["data"]["kind"] == "data"
    assert result["cases"]["blob"]["kind"] == "blob"
    assert result["cases"]["http"]["kind"] == "http"
    assert result["cases"]["empty"]["kind"] == "other"
    # /assets/output/xxx.png 与 /output/xxx.png 语义一致（都属于本地静态挂载）
    assert result["unwrap"]["preview"] == "/output/xxx.png"
    assert result["unwrap"]["download"] == "/output/xxx.png"
    assert result["unwrap"]["direct"] == "/output/xxx.png"
    # 预览 URL 生成对齐 canvas.js canvasMediaPreviewUrl 签名
    assert result["previewOutput"] == "/api/media-preview?w=512&url=%2Foutput%2Fxxx.png"
    assert result["previewAssets"] == "/api/media-preview?w=512&url=%2Fassets%2Foutput%2Fxxx.png"
    # inline 下载 URL 保留 inline=1（补 canvas.js canvasProxiedMediaUrl 语义）
    assert "inline=1" in result["downloadInline"]
    assert "url=%2Foutput%2Fxxx.png" in result["downloadInline"]
    assert result["isLocalOutput"] is True
    assert result["isLocalAssets"] is True
    assert result["isLocalHttp"] is False


def test_file_api_view_matches_legacy_url_resolver_and_upload_uses_fetch():
    """fileApi.view = unwrapMediaPreviewUrl；fileApi.upload 使用 apiClient.post。"""
    result = run_node(
        f"""
        import {{ fileApi }} from {json.dumps(FILE_API)};
        // 模拟一个 fetch 返回：断言 upload 会送出 POST /api/upload + FormData body
        const calls = [];
        globalThis.fetch = async (url, init) => {{
          calls.push({{url, method: init.method, hasFormData: init.body instanceof (globalThis.FormData || function(){{}})}});
          return {{
            ok: true,
            status: 200,
            headers: {{ get: () => 'application/json' }},
            json: async () => ({{ files: [{{ comfy_name: 'x.png' }}] }}),
          }};
        }};
        globalThis.FormData = class FormData {{ append() {{}} }};
        const form = new globalThis.FormData();
        const uploaded = await fileApi.upload(form);
        // 三种 URL 走 view 后都应产出真实资源 URL
        const views = {{
          direct: fileApi.view('/output/xxx.png'),
          preview: fileApi.view('/api/media-preview?w=512&url=%2Foutput%2Fxxx.png'),
          download: fileApi.view('/api/download-output?url=%2Foutput%2Fxxx.png&name=xxx'),
          equal_assets_output: fileApi.view('/api/media-preview?w=512&url=%2Fassets%2Foutput%2Fxxx.png'),
        }};
        console.log(JSON.stringify({{ calls, uploaded, views }}));
        """
    )
    # upload 送出的 URL / method / body 类型对齐旧 fetch('/api/upload', {{method:'POST', body:form}})
    assert len(result["calls"]) == 1
    assert result["calls"][0]["url"] == "/api/upload"
    assert result["calls"][0]["method"] == "POST"
    assert result["uploaded"]["files"][0]["comfy_name"] == "x.png"
    # view() 与 legacyUrlResolver 一致
    assert result["views"]["direct"] == "/output/xxx.png"
    assert result["views"]["preview"] == "/output/xxx.png"
    assert result["views"]["download"] == "/output/xxx.png"
    assert result["views"]["equal_assets_output"] == "/assets/output/xxx.png"


def test_endpoints_module_exports_file_media_constants():
    result = run_node(
        f"""
        import * as ep from {json.dumps(ENDPOINTS)};
        console.log(JSON.stringify({{
          UPLOAD: ep.UPLOAD,
          AI_UPLOAD: ep.AI_UPLOAD,
          MEDIA_PREVIEW: ep.MEDIA_PREVIEW,
          DOWNLOAD_OUTPUT: ep.DOWNLOAD_OUTPUT,
          apiViewNoParams: ep.API_VIEW(),
          apiViewWithParams: ep.API_VIEW({{filename:'x.png'}}),
        }}));
        """
    )
    assert result["UPLOAD"] == "/api/upload"
    assert result["AI_UPLOAD"] == "/api/ai/upload"
    assert result["MEDIA_PREVIEW"] == "/api/media-preview"
    assert result["DOWNLOAD_OUTPUT"] == "/api/download-output"
    assert result["apiViewNoParams"] == "/api/view"
    assert result["apiViewWithParams"] == "/api/view?filename=x.png"


def test_media_bootstrap_script_registers_window_globals_and_is_module_free():
    """bootstrap.js 是非模块脚本，通过动态 import 装配 window.MediaEditor / fileApi / LegacyUrlResolver。"""
    assert BOOTSTRAP.exists(), "shared/media/bootstrap.js 缺失"
    text = BOOTSTRAP.read_text(encoding="utf-8")
    # 非模块（IIFE）；不能出现顶层 import / export
    assert "\nimport " not in "\n" + text, "bootstrap.js 不应包含顶层 import"
    assert "\nexport " not in "\n" + text, "bootstrap.js 不应包含 export"
    # 关键 window 键必须挂上
    for key in ("MediaEditor", "MediaEditorReady", "fileApi", "LegacyUrlResolver"):
        assert key in text, f"bootstrap.js 缺少 window.{key} 装配"
    # 动态 ESM import 必须指向本 PR 落地的三个模块
    assert "/static/js/shared/media/MediaEditor/index.js" in text
    assert "/static/js/shared/api-client/domains/fileApi.js" in text
    assert "/static/js/shared/media/legacyUrlResolver.js" in text


def test_canvas_html_and_smart_canvas_html_include_media_bootstrap():
    for html in ("static/canvas.html", "static/smart-canvas.html"):
        content = (ROOT / html).read_text(encoding="utf-8")
        assert "/static/js/shared/media/bootstrap.js" in content, f"{html} 未引入 shared/media/bootstrap.js"


def test_no_bare_upload_fetch_in_canvas_and_smart_canvas():
    """canvas.js / smart-canvas.js 内 `/api/upload` 裸 fetch 已迁移到 fileApi.upload（PR-4）。"""
    for path in ("static/js/canvas.js", "static/js/smart-canvas.js"):
        content = (ROOT / path).read_text(encoding="utf-8")
        assert "fetch('/api/upload'" not in content, f"{path} 仍存在裸 fetch('/api/upload')"
        assert 'fetch("/api/upload"' not in content, f"{path} 仍存在裸 fetch(\"/api/upload\")"
        assert "fileApi.upload" in content, f"{path} 未消费 fileApi.upload"


def test_media_editor_wrappers_exist_in_canvas_and_smart_canvas():
    """openCropDialog / openMaskDialog / openGridSplitDialog / openInpaintDialog wrapper 存在。"""
    classic = (ROOT / "static/js/canvas.js").read_text(encoding="utf-8")
    for wrapper in ("openCropDialog", "openMaskDialog", "openGridSplitDialog", "openInpaintDialog"):
        assert f"window.{wrapper}" in classic, f"canvas.js 缺少 window.{wrapper} wrapper"
    smart = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
    for wrapper in ("openCropDialog", "openMaskDialog", "openGridSplitDialog", "openInpaintDialog", "openGridJoinDialog"):
        assert f"window.{wrapper}" in smart, f"smart-canvas.js 缺少 window.{wrapper} wrapper"
