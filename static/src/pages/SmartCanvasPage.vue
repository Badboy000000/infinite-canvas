<template>
  <div id="smartCanvasShell" class="shell">
    <div id="smartCanvasWorld" class="world">
      <div class="composer">
        <div class="composer-card">
          <div class="composer-head">
            <div class="composer-head-left">
              <select class="engine-select" aria-label="生成引擎">
                <option value="api">API 生成</option>
                <option value="volcengine">火山引擎</option>
                <option value="modelscope">MS 生成</option>
                <option value="comfy">ComfyUI 生成</option>
                <option value="runninghub">RunningHub</option>
              </select>
            </div>
          </div>

          <div class="prompt-row">
            <div class="prompt-input" contenteditable="true" role="textbox" aria-label="提示词输入"
                 data-placeholder="描述你想生成或编辑的图片..."></div>
            <button class="composer-template-btn" type="button" title="模板库" aria-label="模板库">
              <span>模板库</span>
            </button>
          </div>

          <div class="param-row">
            <div class="dynamic-params"></div>
          </div>

          <div class="composer-actions">
            <button class="run-btn" type="button" aria-label="运行">
              <span>运行</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <button class="smart-back" type="button" aria-label="返回画布列表">
      <span>返回画布列表</span>
    </button>
    <div class="smart-title">智能画布</div>

    <aside class="smart-toolbar" aria-label="智能画布工具栏">
      <button type="button" class="toolbar-btn" aria-label="上传"><span>上传</span></button>
      <button type="button" class="toolbar-btn" aria-label="分组"><span>分组</span></button>
      <button type="button" class="toolbar-btn" aria-label="提示词"><span>提示词</span></button>
      <button type="button" class="toolbar-btn" aria-label="循环"><span>循环</span></button>
    </aside>
  </div>
</template>

<script setup>
console.log('[Vue] SmartCanvasPage mounted')
</script>
