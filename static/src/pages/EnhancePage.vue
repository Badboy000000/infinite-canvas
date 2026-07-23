<template>
  <div class="container-box">
    <header class="flex flex-col md:flex-row justify-between items-end mb-16 gap-6">
      <div class="space-y-1">
        <h1 class="text-4xl font-extrabold tracking-[-0.05em] flex items-center">
          Z IMAGE<span class="text-base mt-3 ml-1">&#174;</span>
        </h1>
        <p class="text-[10px] font-bold uppercase tracking-[0.5em] text-gray-400">Computational Photography Archive</p>
      </div>
      <nav class="flex gap-8 text-[11px] font-bold uppercase tracking-widest text-gray-500">
        <span class="text-black border-b-2 border-black pb-1">Enhance</span>
      </nav>
    </header>

    <main class="grid grid-cols-1 lg:grid-cols-12 gap-12">
      <div class="lg:col-span-4 space-y-10">
        <section class="group">
          <h3 class="text-[9px] font-black uppercase tracking-[0.3em] mb-5 text-gray-400">01. Input Source</h3>
          <div class="upload-item relative overflow-hidden rounded-2xl aspect-[4/3] flex flex-col items-center justify-center cursor-pointer">
            <div class="text-center space-y-4">
              <div class="w-14 h-14 rounded-full border border-gray-200 bg-white flex items-center justify-center mx-auto transition-all duration-500">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              </div>
              <p class="text-[11px] font-bold uppercase tracking-tight">Drop image here</p>
            </div>
          </div>
        </section>

        <section class="space-y-10">
          <h3 class="text-[9px] font-black uppercase tracking-[0.3em] text-gray-400">02. Parameters</h3>
          <div class="space-y-5">
            <div class="flex justify-between items-end">
              <label class="text-xs font-bold uppercase tracking-tight text-gray-800">Refinement Strength</label>
              <span class="font-mono text-xs font-bold">0.50</span>
            </div>
            <input type="range" min="0.1" max="1.0" step="0.01" value="0.5" class="w-full">
          </div>

          <div class="p-5 bg-white border border-gray-200/50 rounded-2xl shadow-sm">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-4">
                <div class="p-2.5 bg-gray-50 rounded-xl border border-gray-100">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
                </div>
                <div>
                  <p class="text-[11px] font-bold uppercase">Super Resolution</p>
                  <p class="text-[9px] text-gray-400">Double pixels (4K)</p>
                </div>
              </div>
              <label class="ios-switch relative inline-block w-12 h-7">
                <input type="checkbox" class="opacity-0 w-0 h-0">
                <span class="ios-slider absolute inset-0 cursor-pointer bg-gray-200 rounded-full transition-colors duration-300"></span>
              </label>
            </div>
          </div>

          <button class="glass-btn w-full py-5 text-white rounded-xl font-bold text-[11px] uppercase tracking-[0.4em] flex items-center justify-center gap-3 shadow-xl shadow-black/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-yellow-400"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <span>Begin Remastering</span>
          </button>
        </section>
      </div>

      <div class="lg:col-span-8">
        <div class="result-frame relative h-[500px] lg:h-[650px] flex items-center justify-center overflow-hidden group">
          <div class="text-center space-y-4 opacity-20">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mx-auto"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            <p class="text-[10px] font-black tracking-[0.5em] uppercase">Canvas Ready</p>
          </div>
        </div>
      </div>
    </main>

    <section class="mt-32">
      <div class="flex items-center gap-6 mb-10">
        <h2 class="text-[11px] font-black uppercase tracking-[0.5em]">Archive</h2>
        <div class="h-px flex-1 bg-black/5"></div>
      </div>
      <div class="masonry-grid"></div>
      <div class="py-16 text-center opacity-20 text-[10px] font-bold uppercase tracking-widest">End of Archive</div>
    </section>
  </div>
</template>

<script setup>
console.log('[Vue] EnhancePage mounted')
</script>