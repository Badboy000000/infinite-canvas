// static/js/shared/components/Can/index.js
//
// Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 · <Can> 骨架.
//
// 契约([[前端组件化治理实施计划与PR清单]] §PR-9):
//
//   - seam 期以 template 属性 `data-can="canvas.edit"` 形式声明动作 · 消费方在
//     DOM 挂载后调用 `Can.autoMount(root, sessionStore)` 自动遍历并 attach。
//   - `mount(element, sessionStore, action)` · 订阅 sessionStore.capabilities:
//     * true / 未登记 → 显示(硬约束:capabilities 未登记透明放行)
//     * false → hide(display:none) · **不移除 DOM**(可回滚)
//   - `unmount(element)` · 撤销订阅 · 恢复 display · 不留监听
//   - **权限未上线全 true 透明放行**(硬约束):sessionStore 默认 capabilities 全 true
//     → 所有 element 可见。
//   - **前端不作为安全事实源**(硬约束):Can 只做 UI 优化 · 后端 401/403 才是权威。
//
// 消费方式(HTML):
//   <button data-can="provider.delete" onclick="deleteProvider()">删除</button>
//   <script>
//     window.SessionStoreReady.then(({ sessionStore, Can }) => {
//       Can.autoMount(document.body, sessionStore);
//     });
//   </script>

import { hasCapability } from '../../stores/sessionStore.js';

// element → { unsubscribe, originalDisplay, action }
const mountedRegistry = new WeakMap();

/**
 * 内部:根据 capabilities 与 action 更新 element 显隐。
 * @param {Element} element
 * @param {object}  capabilities  sessionStore.state.capabilities
 * @param {string}  action
 */
function applyVisibility(element, capabilities, action) {
  if (!element || !element.style) return;
  const allowed = hasCapability(capabilities, action);
  const entry = mountedRegistry.get(element);
  if (allowed) {
    // 恢复原 display(mount 前保存 · null / 空表示浏览器默认)
    element.style.display = entry && entry.originalDisplay != null ? entry.originalDisplay : '';
    // aria-hidden 清理(如果之前被 Can 隐藏过)
    if (element.getAttribute && element.getAttribute('data-can-hidden') === '1') {
      element.removeAttribute('data-can-hidden');
      if (element.removeAttribute) element.removeAttribute('aria-hidden');
    }
  } else {
    // 隐藏但保留 DOM(可回滚 · 硬约束)
    element.style.display = 'none';
    if (element.setAttribute) {
      element.setAttribute('data-can-hidden', '1');
      element.setAttribute('aria-hidden', 'true');
    }
  }
}

/**
 * mount:订阅 sessionStore.capabilities · 立即 apply 一次 · 幂等。
 *
 * @param {Element} element
 * @param {object}  sessionStore  { state, subscribe }(createStore 产物)
 * @param {string}  action        capabilities 键(如 `provider.delete`)
 * @returns {() => void}          unmount 函数
 */
export function mount(element, sessionStore, action) {
  if (!element || !sessionStore || typeof sessionStore.subscribe !== 'function') {
    return function noop() {};
  }
  // 幂等:重复 mount 同一 element 先 unmount 老订阅
  const existing = mountedRegistry.get(element);
  if (existing) {
    try { existing.unsubscribe(); } catch (e) { /* ignore */ }
    mountedRegistry.delete(element);
  }
  const originalDisplay = element.style && 'display' in element.style ? element.style.display : '';
  const entry = { unsubscribe: null, originalDisplay, action: String(action || '') };
  mountedRegistry.set(element, entry);

  // 立即 apply 一次(sessionStore 已有 state)
  applyVisibility(element, sessionStore.state ? sessionStore.state.capabilities : null, entry.action);

  // 订阅 sessionStore 变化 · 每次 revision 变化时重新 apply
  const unsubscribe = sessionStore.subscribe((state /* , revision, reason */) => {
    applyVisibility(element, state ? state.capabilities : null, entry.action);
  });
  entry.unsubscribe = unsubscribe;

  return function unmountBinding() {
    unmount(element);
  };
}

/**
 * unmount:撤销订阅 · 恢复 display · 清 registry。
 * @param {Element} element
 */
export function unmount(element) {
  if (!element) return;
  const entry = mountedRegistry.get(element);
  if (!entry) return;
  try { if (typeof entry.unsubscribe === 'function') entry.unsubscribe(); }
  catch (e) { /* ignore */ }
  if (element.style && entry.originalDisplay != null) {
    element.style.display = entry.originalDisplay;
  }
  if (element.removeAttribute) {
    element.removeAttribute('data-can-hidden');
    element.removeAttribute('aria-hidden');
  }
  mountedRegistry.delete(element);
}

/**
 * autoMount:遍历 root 下所有 `[data-can]` 元素并挂载。
 *
 * @param {Element} root  容器(通常 document.body)
 * @param {object}  sessionStore
 * @returns {number} 挂载元素数
 */
export function autoMount(root, sessionStore) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  const nodes = root.querySelectorAll('[data-can]');
  let count = 0;
  nodes.forEach((el) => {
    const action = el.getAttribute ? el.getAttribute('data-can') : null;
    if (action) {
      mount(el, sessionStore, action);
      count += 1;
    }
  });
  return count;
}

/** 测试用:重置 registry(WeakMap 由 GC 清理 · 此函数只是 no-op 兼容出口) */
export function _resetForTests() {
  // WeakMap 无 clear() 兼容;测试通过独立 element 即可避免污染。
}

const Can = Object.freeze({
  mount,
  unmount,
  autoMount,
  _resetForTests,
});

export default Can;
