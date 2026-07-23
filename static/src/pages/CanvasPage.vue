<template>
  <div id="shell" class="shell no-canvas">
    <div class="topbar">
      <div class="panel canvas-nav">
        <button
          id="backToManagerBtn"
          class="tool-btn"
          type="button"
          title="返回画布管理"
          aria-label="返回画布管理"
        >
          <span>返回</span>
        </button>
        <div class="canvas-nav-meta">
          <div id="currentCanvasTitle" class="current-canvas-title">未命名画布</div>
          <div id="currentCanvasTime" class="current-canvas-time">--</div>
        </div>
      </div>

      <div id="quickToolbar" class="panel toolbar editor-only collapsed" role="toolbar" aria-label="画布快捷工具栏">
        <div class="toolbar-items">
          <button class="tool-btn" type="button" data-action="addImageNode"><span>图片</span></button>
          <button class="tool-btn" type="button" data-action="addPromptNode"><span>提示词</span></button>
          <button class="tool-btn" type="button" data-action="addLLMNode"><span>LLM</span></button>
          <button class="tool-btn" type="button" data-action="addGeneratorNode"><span>API生成</span></button>
          <button class="tool-btn" type="button" data-action="addOutputNode"><span>Output</span></button>
        </div>
      </div>
    </div>

    <div id="board" class="board editor-only" role="region" aria-label="画布编辑区">
      <div id="world" class="world">
        <svg id="links" class="links"></svg>
        <div id="nodes"></div>
      </div>
      <div id="minimap" class="minimap" title="导航地图">
        <div id="minimapContent" class="minimap-content">
          <div id="minimapViewport" class="minimap-viewport"></div>
        </div>
      </div>
    </div>

    <div id="canvasStatus" class="ws-status" aria-live="polite"></div>
  </div>
</template>

<script setup>
console.log('[Vue] CanvasPage mounted')
</script>
