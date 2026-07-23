<template>
  <div id="workspace" class="workspace">
    <aside id="sidebar" class="ws-sidebar">
      <div class="ws-side-head">
        <div class="ws-side-title">项目</div>
        <button id="newProjectBtn" class="ws-side-add" type="button" title="新建项目" aria-label="新建项目">
          <span>+</span>
        </button>
      </div>
      <div id="newProjectRow" class="ws-newproj-row">
        <input id="newProjectInput" class="ws-newproj-input" type="text" maxlength="60" placeholder="项目名称">
        <button id="newProjectConfirm" class="ws-mini-btn primary" type="button" title="确定" aria-label="确定">OK</button>
        <button id="newProjectCancel" class="ws-mini-btn" type="button" title="取消" aria-label="取消">X</button>
      </div>
      <div id="projectList" class="ws-project-list"></div>
      <div class="ws-side-foot">
        <button id="trashEntry" class="ws-trash-entry" type="button">
          <span class="ws-trash-label">回收站</span>
          <span id="trashBadge" class="ws-trash-badge">0</span>
        </button>
      </div>
    </aside>

    <main class="ws-main">
      <div class="ws-topbar">
        <div class="ws-topbar-left">
          <div id="boardProjectName" class="ws-board-name">默认项目</div>
          <span id="boardCanvasCount" class="ws-board-count">0</span>
        </div>
        <div class="ws-topbar-right">
          <button id="boardRefresh" class="ws-icon-btn" type="button" title="刷新" aria-label="刷新">刷新</button>
          <button id="newCanvasBtn" class="ws-primary-btn" type="button"><span>新建画布</span></button>
        </div>
      </div>

      <div id="board" class="ws-board">
        <div id="boardWorld" class="ws-board-world"></div>
        <div id="boardEmptyHint" class="ws-board-empty">
          <div class="ws-board-empty-text">暂无画布</div>
          <div class="ws-board-empty-sub">为当前项目创建第一块画布</div>
          <div class="ws-board-empty-actions">
            <button id="emptyCreateCanvasBtn" class="ws-primary-btn" type="button"><span>新建画布</span></button>
          </div>
        </div>
      </div>

      <div id="trashPanel" class="ws-trash-panel">
        <div class="ws-trash-head">
          <div class="ws-trash-head-title"><span>回收站</span></div>
          <button id="trashClose" class="ws-icon-btn" type="button" title="关闭" aria-label="关闭">X</button>
        </div>
        <div class="ws-trash-note"><span>回收站中的画布会在 30 天后自动清理。</span></div>
        <div id="trashList" class="ws-trash-list"></div>
      </div>

      <div id="boardStatus" class="ws-status"></div>
    </main>
  </div>
</template>

<script setup>
console.log('[Vue] CanvasListPage mounted')
</script>
