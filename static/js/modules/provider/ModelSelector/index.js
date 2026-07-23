// static/js/modules/provider/ModelSelector/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 · 候选 A 配套 ProviderSelector 的 ModelSelector。
//
// 契约(硬约束):
//   - mount(container, {providerId, value?, onChange?, modelKind?})
//     -> {unmount, refresh, setProviderId, setValue, getValue}
//   - 内部渲染 `<select>` · options 来自当前 provider 的 model 列表
//   - providerId 变更时 · value 重置为该 provider 的第一个 model(**T333 契约**)
//   - **P0 密钥零渲染防线**:同 ProviderSelector,只读白名单字段 · sentinel 反查
//   - **P0 XSS 抗回归**:model.id / model.display_name 走 escapeHtml/escapeAttr
//
// 零构建 / 零依赖 / native ES module。

import { providersStore } from '../../../shared/stores/providersStore.js';
import { pickWhitelist, FORBIDDEN_DOM_SENTINELS } from '../ProviderSelector/index.js';

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

// Model 白名单字段(与 ProviderSelector.WHITELIST 一致的 spirit,只是范围收窄到
// model info)。禁止字段:api_key/secret/token/password/credential/raw。
export const MODEL_WHITELIST_FIELDS = Object.freeze([
    'id', 'display_name', 'name', 'kind',
]);

/** Extract model list from a provider payload — 只读 whitelisted provider.models。 */
export function extractModels(provider, modelKind) {
    const safe = pickWhitelist(provider);
    if (!safe || !Array.isArray(safe.models)) return [];
    // model 可能是 string(legacy)或 object {id, display_name, kind, ...}。
    const list = safe.models.map((m) => {
        if (m == null) return null;
        if (typeof m === 'string') return { id: m, display_name: m };
        if (typeof m !== 'object') return null;
        const out = {};
        MODEL_WHITELIST_FIELDS.forEach((k) => { if (k in m) out[k] = m[k]; });
        return (out.id || out.name) ? { id: out.id || out.name, display_name: out.display_name || out.id || out.name, kind: out.kind } : null;
    }).filter(Boolean);
    if (!modelKind) return list;
    return list.filter((m) => !m.kind || m.kind === modelKind);
}

function _findProvider(providerId) {
    const list = (providersStore.state && Array.isArray(providersStore.state.providers))
        ? providersStore.state.providers : [];
    return list.find((p) => p && p.id === providerId) || null;
}

/**
 * @param {HTMLElement} container
 * @param {object} opts
 * @param {string}   opts.providerId
 * @param {string}   [opts.value]
 * @param {(modelId:string)=>void} [opts.onChange]
 * @param {string}   [opts.modelKind]   optional filter e.g. 'image' / 'chat'
 */
export function mount(container, opts) {
    const options = opts || {};
    if (!container || !container.appendChild) {
        throw new Error('ModelSelector.mount: 需要 container HTMLElement');
    }
    if (container.__modelSelectorInstance) {
        try { container.__modelSelectorInstance.unmount(); } catch (_) { /* noop */ }
    }

    let providerId = options.providerId == null ? '' : String(options.providerId);
    let currentValue = options.value == null ? '' : String(options.value);
    const modelKind = options.modelKind || '';

    const selectId = `msel-${Math.random().toString(36).slice(2, 8)}`;
    container.innerHTML = `<select class="sc-model-select" data-role="model-select" id="${selectId}"></select>`;
    const select = container.querySelector(`#${CSS.escape(selectId)}`);

    function _models() {
        return extractModels(_findProvider(providerId), modelKind);
    }

    function refresh() {
        const models = _models();
        if (!models.some((m) => m.id === currentValue)) {
            currentValue = models[0] ? models[0].id : '';
        }
        select.innerHTML = models.map((m) => {
            const label = m.display_name || m.id;
            const sel = m.id === currentValue ? 'selected' : '';
            return `<option value="${escapeAttr(m.id)}" ${sel}>${escapeHtml(label)}</option>`;
        }).join('');
        select.value = currentValue;
    }

    function _onChange(e) {
        const v = e && e.target ? String(e.target.value || '') : '';
        currentValue = v;
        if (typeof options.onChange === 'function') {
            try { options.onChange(v); } catch (err) {
                if (typeof console !== 'undefined' && console.error) console.error('[ModelSelector] onChange', err);
            }
        }
    }
    select.addEventListener('change', _onChange);

    const unsubscribe = providersStore.subscribe(() => { refresh(); });
    refresh();

    let unmounted = false;
    function unmount() {
        if (unmounted) return;
        unmounted = true;
        try { unsubscribe && unsubscribe(); } catch (_) { /* noop */ }
        try { select.removeEventListener('change', _onChange); } catch (_) { /* noop */ }
        container.innerHTML = '';
        container.__modelSelectorInstance = null;
    }

    function setProviderId(id) {
        providerId = id == null ? '' : String(id);
        // T333 契约:换 provider 后 value 重置为空,让 refresh 挑第一个 model。
        currentValue = '';
        refresh();
        // 触发 onChange 通知(currentValue 已在 refresh 内被填成第一个 model)
        if (typeof options.onChange === 'function') {
            try { options.onChange(currentValue); } catch (_) { /* noop */ }
        }
    }
    function setValue(v) { currentValue = v == null ? '' : String(v); refresh(); }
    function getValue() { return currentValue; }

    const instance = { unmount, refresh, setProviderId, setValue, getValue, root: container };
    container.__modelSelectorInstance = instance;
    return instance;
}

export function unmount(container) {
    if (container && container.__modelSelectorInstance) {
        try { container.__modelSelectorInstance.unmount(); } catch (_) { /* noop */ }
    }
}

const ModelSelector = { mount, unmount, extractModels, MODEL_WHITELIST_FIELDS, FORBIDDEN_DOM_SENTINELS };
export default ModelSelector;
