<template>
  <div class="page">
    <div class="wrap">
      <header class="page-head">
        <div>
          <div class="title">API 设置</div>
          <div class="sub">管理平台地址、模型列表和 Key。Key 写入后端 env，页面不会回显完整内容。</div>
        </div>
        <div class="status" role="status" aria-live="polite"></div>
      </header>

      <div class="layout">
        <aside class="sidebar" aria-label="平台列表">
          <div class="side-section-title">平台列表</div>
          <div class="provider-list" role="list"></div>
          <button class="add-btn" type="button">
            <span>+ 新增平台</span>
          </button>
          <button class="api-link-btn" type="button">
            <span>推荐 API</span>
          </button>
          <div class="cli-quick-group">
            <div class="side-section-title">CLI 设置</div>
            <div class="cli-quick-list">
              <button class="cli-quick-btn" type="button"><span>即梦 CLI</span></button>
              <button class="cli-quick-btn" type="button"><span>GPT CLI</span></button>
              <button class="cli-quick-btn" type="button"><span>Antigravity CLI</span></button>
              <div class="cli-quick-note">需要先安装 CLI 文件夹中的依赖。</div>
            </div>
          </div>
        </aside>

        <main class="content" aria-label="平台配置编辑区">
          <div class="content-head">
            <div>
              <div class="editor-title">平台</div>
              <div class="editor-sub">配置基础信息、API Key 和可用模型</div>
            </div>
            <div class="content-actions">
              <button class="action-btn danger-btn" type="button">删除</button>
              <button class="action-btn save-btn" type="button">保存</button>
            </div>
          </div>

          <section class="block">
            <div class="block-head">
              <div>
                <div class="block-title">基本信息</div>
                <div class="block-desc">平台显示名、唯一 ID 和请求地址</div>
              </div>
            </div>
            <div class="form">
              <label class="field full">
                <span class="label">平台名称</span>
                <div class="field-frame"><input type="text" placeholder="Comfly"></div>
              </label>
              <label class="field full">
                <span class="label">请求地址</span>
                <div class="field-frame"><input type="text" placeholder="https://api.example.com/v1"></div>
              </label>
            </div>
          </section>

          <section class="block">
            <div class="block-head">
              <div>
                <div class="block-title">API Key</div>
                <div class="block-desc">Key 写入后端 env，页面不会回显完整内容</div>
              </div>
            </div>
            <div class="form">
              <label class="field full">
                <span class="label">API Key</span>
                <div class="field-frame"><input type="password" placeholder="sk-..."></div>
              </label>
            </div>
          </section>

          <section class="block">
            <div class="block-head">
              <div>
                <div class="block-title">可用模型</div>
                <div class="block-desc">配置此平台支持的模型列表</div>
              </div>
            </div>
            <div class="model-list" role="list"></div>
          </section>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
// PR-12 · api-settings SPA 骨架迁移 · Wave 3-N.7 Batch 5 主线 A
// 说明:骨架迁移,UI 布局 + 基本交互占位,legacy static/api-settings.html 保留承担实际功能。
// 后续 PR 再接入 provider store / Key 保存 / 模型抓取等业务逻辑。
console.log('[Vue] ApiSettingsPage mounted')
</script>
