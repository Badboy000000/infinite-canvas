<template>
  <div class="page">
    <div class="wrap">
      <header class="page-head">
        <div>
          <div class="title" data-i18n="comfy.title">工作流设置</div>
          <div class="sub" data-i18n="comfy.subtitle">选择本地 ComfyUI 工作流，配置可暴露到画布的输入参数。</div>
        </div>
        <div id="status" class="status"></div>
      </header>

      <div class="layout">
        <aside class="sidebar">
          <div class="side-card workflow-panel workflow-panel-comfy">
            <div class="side-title">ComfyUI 后端地址</div>
            <div id="comfyInstancesList" class="comfy-instances-list"></div>
            <button class="upload-btn" type="button">
              <span>添加后端</span>
            </button>
            <div class="hint">格式：<span class="mono">host:port</span>（如 <span class="mono">127.0.0.1:8188</span>）</div>
          </div>

          <div class="side-card workflow-panel workflow-panel-comfy">
            <div class="side-title" data-i18n="comfy.workflowList">工作流列表</div>
            <div id="workflowList" class="workflow-list"></div>
            <button class="upload-btn" type="button">
              <span data-i18n="comfy.uploadWorkflow">上传工作流</span>
            </button>
          </div>

          <div class="side-card" id="previewCard">
            <div class="preview-title-row">
              <div class="preview-title" data-i18n="comfy.nodePreview">画布节点预览</div>
              <div class="preview-pill" data-i18n="comfy.live">实时</div>
            </div>
            <div class="preview-desc" data-i18n="comfy.previewDesc">这个工作流在画布 Comfy 节点上将显示出的控件。</div>
            <div id="previewContent">
              <div class="preview-empty" data-i18n="comfy.previewEmpty">勾选节点输入字段后预览将出现在这里</div>
            </div>
          </div>
        </aside>

        <main class="content">
          <div id="graphCard" class="graph-card">
            <div class="graph-head">
              <div class="graph-title-row">
                <input class="workflow-title-input" type="text" placeholder="工作流名称" data-i18n-placeholder="comfy.workflowName">
              </div>
            </div>
            <div class="graph-svg-wrap">
              <svg id="graphSvg" class="graph-svg"></svg>
            </div>
          </div>
          <div id="nodeList" class="node-list hidden"></div>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
console.log('[Vue] ComfyuiSettingsPage mounted')
</script>
