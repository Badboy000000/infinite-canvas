<template>
  <div class="container-box">
    <header class="flex flex-col md:flex-row justify-between items-end mb-16 gap-6">
      <div class="space-y-1">
        <h1 class="text-4xl font-extrabold tracking-[-0.05em] flex items-center">
          ANGLE CONTROL<span class="text-base mt-3 ml-1">&#174;</span>
        </h1>
        <p class="text-[10px] font-bold uppercase tracking-[0.5em] text-gray-400">Camera &amp; Perspective Control</p>
      </div>
      <nav class="flex gap-8 text-[11px] font-bold uppercase tracking-widest text-gray-500">
        <span class="text-black border-b-2 border-black pb-1">Angle</span>
      </nav>
    </header>

    <main class="space-y-12">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-10 items-start">
        <section class="group w-full">
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

        <section class="space-y-6 w-full">
          <h3 class="text-[9px] font-black uppercase tracking-[0.3em] text-gray-400">02. Camera Control</h3>
          <div class="w-full aspect-[4/3] flex flex-col md:flex-row bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <div class="relative flex-1 bg-[#222] h-full min-h-0 flex items-center justify-center">
              <span class="text-white/30 text-[10px] font-bold uppercase tracking-widest">3D Preview</span>
            </div>
            <div class="w-full md:w-64 flex-shrink-0 p-5 flex flex-col justify-center gap-4 border-l border-gray-100 bg-white overflow-y-auto">
              <div class="space-y-3">
                <div class="flex justify-between items-center text-[10px] font-bold uppercase tracking-wider text-gray-500">
                  <div class="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
                    <span>Rotation</span>
                  </div>
                  <div class="flex items-center bg-gray-100 rounded-md px-2">
                    <input type="number" value="0" class="w-10 bg-transparent py-1 text-black text-center outline-none border-none p-0 text-[10px] font-bold">
                    <span class="text-gray-400 select-none text-[10px]">&#176;</span>
                  </div>
                </div>
                <input type="range" min="-90" max="90" value="0" class="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-black">
              </div>
              <div class="space-y-3">
                <div class="flex justify-between items-center text-[10px] font-bold uppercase tracking-wider text-gray-500">
                  <div class="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
                    <span>Pitch</span>
                  </div>
                  <div class="flex items-center bg-gray-100 rounded-md px-2">
                    <input type="number" value="0" class="w-10 bg-transparent py-1 text-black text-center outline-none border-none p-0 text-[10px] font-bold">
                    <span class="text-gray-400 select-none text-[10px]">&#176;</span>
                  </div>
                </div>
                <input type="range" min="-90" max="90" value="0" class="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-black">
              </div>
              <div class="space-y-3">
                <div class="flex justify-between items-center text-[10px] font-bold uppercase tracking-wider text-gray-500">
                  <div class="flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    <span>Distance</span>
                  </div>
                  <div class="flex items-center bg-gray-100 rounded-md px-2">
                    <input type="number" value="4.0" step="0.1" class="w-10 bg-transparent py-1 text-black text-center outline-none border-none p-0 text-[10px] font-bold">
                  </div>
                </div>
                <input type="range" min="0.1" max="8" value="4" step="0.1" class="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-black">
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-10 items-stretch">
        <section class="flex flex-col space-y-6">
          <h3 class="text-[9px] font-black uppercase tracking-[0.3em] text-gray-400">03. Parameters</h3>
          <div class="space-y-3 flex-1 flex flex-col">
            <div class="flex items-center gap-2 text-gray-800 ml-1">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              <span class="text-[10px] font-bold uppercase tracking-widest">Prompt</span>
            </div>
            <textarea class="nano-input w-full flex-1 p-5 text-sm outline-none resize-none placeholder-gray-300" placeholder="Adjust via controls or enter prompt"></textarea>
          </div>

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

          <button class="glass-btn w-full py-5 text-white rounded-xl font-bold text-[11px] uppercase tracking-[0.4em] flex items-center justify-center gap-3 shadow-xl shadow-black/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-yellow-400"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <span>Generate New Angle</span>
          </button>
        </section>

        <section class="space-y-6 flex flex-col">
          <h3 class="text-[9px] font-black uppercase tracking-[0.3em] text-gray-400">04. Result Preview</h3>
          <div class="result-frame relative aspect-[4/3] w-full flex items-center justify-center overflow-hidden group">
            <div class="text-center space-y-4 opacity-20">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mx-auto"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <p class="text-[10px] font-black tracking-[0.5em] uppercase">Canvas Ready</p>
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup>
console.log('[Vue] AnglePage mounted')
</script>