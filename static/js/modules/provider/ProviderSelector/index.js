// static/js/modules/provider/ProviderSelector/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 · **候选 A GM-14 第 5 次实证**。
//
// 语义分层(硬约束):
//   - 本文件承担 state + lifecycle(mount 订阅 providersStore + change 事件)
//   - `shared/components/ProviderSelector/`(Wave 3-K PR-9 保守渲染层)承担
//     option 序列 HTML 拼接(renderHtml / renderOptionList · zero DOM lifecycle)
//   - 二者平级共存,不同路径
//
// 契约(硬约束):
//   - mount(container, {value, onChange, filterCapability?, variant?})
//     -> {unmount, refresh, setValue, getValue}
//   - 渲染 `<select>` · 由 shared/components/ProviderSelector.renderHtml 生成
//     option 序列 · innerHTML 注入
//   - `providersStore.subscribe` 变化时 refresh
//   - onChange(providerId) 由 select change 事件触发
//
// **P0 密钥零渲染防线(硬约束)**:
//   - `WHITELIST_FIELDS` = `[id, name, protocol, capability, models, icon_url]`
//   - 从 store 取 provider 后,只保留白名单字段传给 renderHtml
//   - 严禁把 `api_key` / `secret` / `token` / `password` / `credential` / `raw`
//     渲染到 DOM 或 window 全局
//   - T332 sentinel 反查通过 grep outerHTML 5 类关键字 = 0 命中
//
// 零构建 / 零依赖 / native ES module。

import { providersStore } from '../../../shared/stores/providersStore.js';
import {
    renderHtml as renderOptionsHtml,
    PROVIDER_SELECTOR_VARIANTS,
} from '../../../shared/components/ProviderSelector/index.js';

// P0 白名单 —— 只有这些字段可以从 provider payload 中被读取传给渲染层。
export const WHITELIST_FIELDS = Object.freeze([
    'id', 'name', 'protocol', 'capability', 'models', 'icon_url',
]);

// P0 sentinel —— 明确禁止出现在任何 DOM 输出的关键字。T332 用 grep 反查。
export const FORBIDDEN_DOM_SENTINELS = Object.freeze([
    'api_key', 'secret', 'token', 'password', 'credential',
]);

/** Pick 白名单字段 —— provider payload 通过此 fn 之后才能进入 renderHtml。 */
export function pickWhitelist(provider) {
    if (!provider || typeof provider !== 'object') return null;
    const out = {};
    WHITELIST_FIELDS.forEach((k) => {
        if (k in provider) out[k] = provider[k];
    });
    return out;
}

/**
 * @param {HTMLElement} container
 * @param {object} opts
 * @param {string}   [opts.value]              初始 providerId
 * @param {(providerId:string)=>void} [opts.onChange]
 * @param {(provider:object)=>boolean} [opts.filterCapability]  可选 predicate
 *          默认全通过。**必须只读白名单字段**(否则 P0 违反)。
 * @param {'chat'|'image'|'video'} [opts.variant='chat']
 * @param {string}   [opts.emptyLabel]          image variant 空 providers 占位文案
 */
export function mount(container, opts) {
    const options = opts || {};
    if (!container || !container.appendChild) {
        throw new Error('ProviderSelector.mount: 需要 container HTMLElement');
    }
    // 幂等:先 unmount 旧实例
    if (container.__providerSelectorInstance) {
        try { container.__providerSelectorInstance.unmount(); } catch (_) { /* noop */ }
    }

    const variant = PROVIDER_SELECTOR_VARIANTS[options.variant] ? options.variant : 'chat';
    let currentValue = options.value == null ? '' : String(options.value);
    const filterFn = typeof options.filterCapability === 'function'
        ? options.filterCapability
        : () => true;

    const selectId = `psel-${Math.random().toString(36).slice(2, 8)}`;
    container.innerHTML = `<select class="sc-provider-select" data-role="provider-select" id="${selectId}"></select>`;
    const select = container.querySelector(`#${CSS.escape(selectId)}`);

    function _visibleProviders() {
        const list = (providersStore.state && Array.isArray(providersStore.state.providers))
            ? providersStore.state.providers : [];
        // 应用 filterCapability 后再 pick 白名单。filter 拿到的 provider 由调用方
        // 承诺**只读白名单字段**;为了硬护栏,即使调用方失守,我们仍在 pick 后传
        // 给 renderHtml,pick 后的对象只含白名单字段。
        return list
            .filter((p) => { try { return filterFn(p); } catch (_) { return false; } })
            .map(pickWhitelist)
            .filter((p) => p && p.id);
    }

    function refresh() {
        const providers = _visibleProviders();
        // 保存 selectedId — 如当前 value 不在可见列表内,尝试保留(便于 store
        // 异步刷新覆盖时不丢用户选择)
        select.innerHTML = renderOptionsHtml(variant, providers, currentValue, {
            emptyLabel: options.emptyLabel || '',
        });
        // Sync <select>.value: reflect either user's chosen or provider list state
        if (providers.some((p) => p.id === currentValue)) {
            select.value = currentValue;
        }
    }

    function _onChange(e) {
        const v = e && e.target ? String(e.target.value || '') : '';
        currentValue = v;
        if (typeof options.onChange === 'function') {
            try { options.onChange(v); } catch (err) {
                if (typeof console !== 'undefined' && console.error) console.error('[ProviderSelector] onChange', err);
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
        container.__providerSelectorInstance = null;
    }

    function setValue(v) {
        currentValue = v == null ? '' : String(v);
        refresh();
    }
    function getValue() { return currentValue; }

    const instance = { unmount, refresh, setValue, getValue, root: container };
    container.__providerSelectorInstance = instance;
    return instance;
}

export function unmount(container) {
    if (container && container.__providerSelectorInstance) {
        try { container.__providerSelectorInstance.unmount(); } catch (_) { /* noop */ }
    }
}

const ProviderSelector = { mount, unmount, pickWhitelist, WHITELIST_FIELDS, FORBIDDEN_DOM_SENTINELS };
export default ProviderSelector;
