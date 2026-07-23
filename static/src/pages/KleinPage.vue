<template>
  <div class="container-box min-h-screen flex flex-col">
    <header class="flex justify-between items-end mb-10">
      <div class="space-y-1">
        <h1 class="text-4xl font-extrabold tracking-tighter italic">FLUX KLEIN</h1>
        <p class="text-[10px] font-bold uppercase tracking-[0.4em] text-gray-400">Next-Gen Generative Interface</p>
      </div>
    </header>

    <main class="grid grid-cols-1 lg:grid-cols-12 gap-12">
      <div class="lg:col-span-5 space-y-10">
        <section class="space-y-4">
          <div class="flex items-center gap-2 text-gray-400">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
            <span class="text-[10px] font-black uppercase tracking-widest">Input Prompt</span>
          </div>
          <textarea rows="5" class="nano-input w-full p-6 rounded-3xl text-sm outline-none resize-none placeholder-gray-300" placeholder="Describe your vision here..."></textarea>
        </section>

        <section class="space-y-4">
          <div class="flex items-center gap-2 text-gray-400">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            <span class="text-[10px] font-black uppercase tracking-widest">Reference Layers</span>
          </div>
          <div class="grid grid-cols-3 gap-4">
            <div class="upload-item group aspect-square rounded-2xl flex flex-col items-center justify-center cursor-pointer">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-300"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span class="text-[9px] mt-2 font-bold text-gray-400 uppercase">Main</span>
            </div>
            <div class="upload-item group aspect-square rounded-2xl flex flex-col items-center justify-center cursor-pointer">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-300"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span class="text-[9px] mt-2 font-bold text-gray-400 uppercase">Aux A</span>
            </div>
            <div class="upload-item group aspect-square rounded-2xl flex flex-col items-center justify-center cursor-pointer">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-300"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span class="text-[9px] mt-2 font-bold text-gray-400 uppercase">Aux B</span>
            </div>
          </div>
        </section>

        <div class="engine-panel">
          <div class="engine-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/></svg>
            <span>Engine</span>
          </div>
          <div class="engine-switch">
            <button class="engine-btn active">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/></svg>
              <span>Local</span>
            </button>
            <button class="engine-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
              ModelScope
            </button>
          </div>
        </div>

        <button class="glass-btn w-full py-5 text-white rounded-xl font-bold flex items-center justify-center gap-3 shadow-lg">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-yellow-400"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span class="tracking-[0.3em] text-[11px] uppercase">Execute Synthesis</span>
        </button>
      </div>

      <div class="lg:col-span-7">
        <div class="result-frame min-h-[500px] lg:h-full flex items-center justify-center relative overflow-hidden group">
          <div class="text-center space-y-4 opacity-20">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mx-auto"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            <p class="text-[10px] font-black tracking-[0.5em] uppercase">Canvas Ready</p>
          </div>
        </div>
      </div>
    </main>

    <section class="mt-32">
      <div class="flex items-center gap-6 mb-12">
        <h2 class="text-[11px] font-black uppercase tracking-[0.5em]">Archives</h2>
        <div class="h-px flex-1 bg-gray-100"></div>
      </div>
      <div class="masonry-grid"></div>
      <div class="py-20 text-center text-gray-300 text-[10px] font-bold uppercase tracking-widest cursor-pointer hover:text-black transition-colors">
        <span>Load More Archive</span>
      </div>
    </section>
  </div>
</template>

<script setup>
console.log('[Vue] KleinPage mounted')
</script>