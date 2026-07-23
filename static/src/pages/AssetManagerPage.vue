<template>
  <div class="asset-page">
    <header class="asset-page-head">
      <div>
        <div class="asset-title">素材库管理</div>
        <div class="asset-sub">按库、分组、内容和预览管理素材与提示词。</div>
      </div>
      <div class="asset-head-actions">
        <div id="assetStatus" class="asset-status">准备就绪</div>
        <button id="storageSettingsBtn" class="asset-btn" type="button"><span>偏好设置</span></button>
        <button id="refreshBtn" class="asset-btn" type="button"><span>刷新</span></button>
      </div>
    </header>

    <div class="asset-tabs">
      <button id="assetTabAssets" class="active" type="button" data-tab="assets"><span>图片资产</span></button>
      <button id="assetTabWorkflows" type="button" data-tab="workflows"><span>工作流管理</span></button>
      <button id="assetTabPrompts" type="button" data-tab="prompts"><span>提示词库</span></button>
      <button id="assetTabCanvasAssets" type="button" data-tab="canvas-assets"><span>画布资产</span></button>
      <button id="assetTabLocal" type="button" data-tab="local"><span>本地素材</span></button>
    </div>

    <main id="assetManagerRoot" class="asset-manager-root"></main>

    <input id="assetUploadInput" type="file" accept="image/*,video/*,audio/*,.json,.zip,application/json,application/zip" multiple hidden>
  </div>
</template>

<script setup>
console.log('[Vue] AssetManagerPage mounted')
</script>
