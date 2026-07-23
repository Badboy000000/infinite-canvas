<template>
  <div>
    <header class="pt-20 pb-12">
      <div class="layout-container">
        <div class="console-card rounded-3xl p-1.5">
          <div class="bg-gray-50/50 rounded-[22px] p-8">
            <div class="flex justify-between items-center mb-6">
              <span class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Unified Art Console</span>
              <div class="flex items-center gap-2">
                <span class="text-[9px] font-bold text-gray-500 uppercase">System Ready</span>
                <div class="w-1.5 h-1.5 bg-black rounded-full"></div>
              </div>
            </div>
            <textarea rows="2" class="w-full bg-transparent text-2xl font-medium outline-none placeholder:text-gray-200 text-black resize-none leading-relaxed" placeholder="Describe your vision..."></textarea>
          </div>

          <div class="flex flex-col md:flex-row items-center justify-between p-4 px-6 gap-6">
            <div class="flex items-center gap-8">
              <div class="flex flex-col">
                <span class="text-[9px] font-bold text-gray-400 uppercase mb-1">Engine Source</span>
                <div class="mode-switcher">
                  <div class="mode-btn active flex items-center justify-center gap-1.5">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                    <span>Local</span>
                  </div>
                  <div class="mode-btn flex items-center justify-center gap-1.5">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
                    <span>ModelScope</span>
                  </div>
                  <div class="mode-glider"></div>
                </div>
              </div>

              <div class="h-8 w-px bg-gray-100"></div>

              <div class="flex flex-col">
                <span class="text-[9px] font-bold text-gray-400 uppercase mb-1">Dimensions</span>
                <div class="flex items-center gap-2 text-xs font-bold">
                  <input type="number" value="1024" class="w-10 bg-transparent outline-none border-b border-transparent focus:border-black">
                  <span class="text-gray-200">&times;</span>
                  <input type="number" value="1024" class="w-10 bg-transparent outline-none border-b border-transparent focus:border-black">
                </div>
              </div>
            </div>

            <button class="w-full md:w-56 h-12 btn-render rounded-xl font-bold text-[11px] uppercase flex items-center justify-center gap-3">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-yellow-400"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>Render Art</span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <main class="pb-24">
      <div class="layout-container">
        <div class="masonry-grid"></div>
        <div class="py-12 text-center text-gray-300 text-[10px] font-bold uppercase tracking-widest cursor-pointer">
          <span>Load More Archive</span>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
console.log('[Vue] ZimagePage mounted')
</script>