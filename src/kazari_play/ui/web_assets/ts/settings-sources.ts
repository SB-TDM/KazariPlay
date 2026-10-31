(function () {
  let generation = 0;
  let loaded = false;

  function empty(text: string): void {
    const box = document.getElementById('setSrcList');
    if (box) box.innerHTML = `<div class="src-empty">${esc(text)}</div>`;
  }

  function load(isCurrent: () => boolean): void {
    const box = document.getElementById('setSrcList');
    if (!bridge || !box) return;
    const request = ++generation;
    loaded = false;
    bridge.getMetadataSources(function (s: unknown, failed?: boolean) {
      if (request !== generation || !isCurrent()) return;
      if (failed) {
        empty('数据源加载失败');
        return;
      }
      let sources: Array<{
        id?: string;
        name?: string;
        icon?: string;
        status?: string;
        enabled?: boolean;
      }> = [];
      try { sources = JSON.parse(String(s || '[]')); } catch (e) { }
      if (!Array.isArray(sources)) sources = [];
      loaded = true;
      if (sources.length === 0) {
        empty('暂无可用数据源');
        return;
      }
      const statusText: Record<string, string> = {
        ready: '可用',
        experimental: '实验性',
        pending: '未接入',
      };
      box.innerHTML = '';
      sources.forEach((src) => {
        const usable = src.status === 'ready' || src.status === 'experimental';
        const row = document.createElement('label');
        row.className = 'src-opt' + (usable ? '' : ' disabled');
        row.innerHTML = `
          <input type="checkbox" class="src-check ui-check" data-id="${esc(src.id)}" ${src.enabled && usable ? 'checked' : ''} ${usable ? '' : 'disabled'}>
          <img class="src-fav" src="${esc(src.icon || '')}" onerror="this.style.display='none'" alt="">
          <span class="src-name">${esc(src.name)}</span>
          <span class="src-status">${esc(statusText[src.status || ''] || src.status || '')}</span>`;
        box.appendChild(row);
      });
    });
  }

  function readChecked(): string[] | null {
    if (!loaded) return null;
    return [...document.querySelectorAll<HTMLElement>('#setSrcList .src-check:checked')]
      .map((item) => item.dataset.id || '')
      .filter(Boolean);
  }

  const kit = window.SettingsKit || (window.SettingsKit = {} as SettingsKitApi);
  kit.sources = { load, readChecked };
})();
