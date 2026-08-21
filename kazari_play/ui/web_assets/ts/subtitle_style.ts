// ============================================================
// subtitle_style.ts — 字幕样式控制面板（设置页「字幕」tab）
// 依赖：core.ts（toast/bridge）
// 定义：window.SubtitleStyle（load）/ window.updateSubtitlePos（拖拽回传）
// 被依赖：settings.ts（Settings.open / 字幕 tab 激活时调用 SubtitleStyle.load）
// ============================================================

/** 字幕样式字段（与 C++ subtitle_style.h / overlay 协议保持一致） */
interface SubtitleStyleFields {
  bg_mode?: number;
  align?: number;
  gradient?: boolean;
  border?: boolean;
  outline?: boolean;
  shadow?: boolean;
  avoid_bottom?: boolean;
  show_source?: boolean;
  bg_r?: number; bg_g?: number; bg_b?: number;
  grad_r?: number; grad_g?: number; grad_b?: number;
  border_r?: number; border_g?: number; border_b?: number;
  text_r?: number; text_g?: number; text_b?: number;
  outline_r?: number; outline_g?: number; outline_b?: number;
  bg_a?: number;
  corner?: number;
  padding?: number;
  border_w?: number;
  font_size?: number;
  font_weight?: number;
  outline_w?: number;
  shadow_off?: number;
  line_gap?: number;
  max_width?: number;
  pos_x?: number;
  pos_y?: number;
  avoid_bottom_px?: number;
  font?: string;
}

(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;

  // ================== 字幕样式（原独立控制面板并入设置页） ==================
  // 控件 id → SubtitleStyle 字段映射；改动实时防抖下发 setSubtitleStyle
  let subStyle: SubtitleStyleFields = {};
  let subPresets: Record<string, SubtitleStyleFields> = {};
  let subPushTimer: ReturnType<typeof setTimeout> | null = null;
  let subLastPushed = '';
  let subDragArmed = false;

  function subToast(msg: string): void { toast(msg); }

  function subRgbToHex(r: number, g: number, b: number): string {
    const c = (v: number): string => { const n = Math.round(v * 255).toString(16); return n.length < 2 ? '0' + n : n; };
    return '#' + c(r) + c(g) + c(b);
  }
  function subHexToRgb(hex: string): { r: number; g: number; b: number } {
    const h = (hex || '#ffffff').replace('#', '');
    return { r: parseInt(h.slice(0, 2), 16) / 255, g: parseInt(h.slice(2, 4), 16) / 255, b: parseInt(h.slice(4, 6), 16) / 255 };
  }

  // 内置预设标签（仅显示用；用户命名预设直接显示名称）
  const SUB_BUILTIN_LABELS: Record<string, string> = { original: '原作风格', minimal: '极简无底板', darkglass: '半透黑底' };

  // 预设下拉动态渲染：内置 3 套 + 用户命名预设
  function subRenderPresets(selected: string): void {
    const sel = $('setSubPreset') as HTMLSelectElement | null;
    if (!sel) return;
    sel.innerHTML = '';
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = '选择预设…';
    sel.appendChild(empty);
    Object.keys(subPresets || {}).forEach((key) => {
      const o = document.createElement('option');
      o.value = key;
      o.textContent = SUB_BUILTIN_LABELS[key] || key;
      sel.appendChild(o);
    });
    if (selected && subPresets[selected]) sel.value = selected;
  }

  function subPush(immediate?: boolean): void {
    const payload = JSON.stringify(subStyle);
    clearTimeout(subPushTimer as ReturnType<typeof setTimeout>);
    if (!immediate && payload === subLastPushed) return;
    const send = (): void => {
      subLastPushed = JSON.stringify(subStyle);
      bridge.setSubtitleStyle(JSON.stringify(subStyle));
    };
    if (immediate) { send(); return; }
    subPushTimer = setTimeout(send, 150);
  }

  // 拖拽结束回传位置 → 更新滑块（web_bridge evaluate_js 调用）
  window.updateSubtitlePos = function (x: number, y: number) {
    subStyle.pos_x = Math.max(0, Math.min(1, x));
    subStyle.pos_y = Math.max(0, Math.min(1, y));
    const vx = $('setSubPosX') as HTMLInputElement | null, vy = $('setSubPosY') as HTMLInputElement | null;
    if (vx) vx.value = String(Math.round(subStyle.pos_x * 100));
    if (vy) vy.value = String(Math.round(subStyle.pos_y * 100));
    const lx = $('setSubPosXV'), ly = $('setSubPosYV');
    if (lx) lx.textContent = vx ? vx.value + '%' : '';
    if (ly) ly.textContent = vy ? vy.value + '%' : '';
    subToast('字幕位置已更新');
  };

  function subApplyStyle(s: SubtitleStyleFields): void {
    subStyle = Object.assign(subStyle, s || {});
    const setChecked = (id: string, v: unknown): void => {
      if (typeof v === 'boolean') ($(id) as HTMLInputElement).checked = v;
    };

    ['setSubBgMode', 'setSubAlign'].forEach((gid) => {
      const g = $(gid); if (!g) return;
      const v = gid === 'setSubBgMode' ? subStyle.bg_mode : subStyle.align;
      g.querySelectorAll<HTMLElement>('.opt').forEach((o) => o.classList.toggle('on', +o.dataset.v! === v));
    });
    setChecked('setSubGradient', subStyle.gradient);
    setChecked('setSubBorder', subStyle.border);
    setChecked('setSubOutline', subStyle.outline);
    setChecked('setSubShadow', subStyle.shadow);
    setChecked('setSubAvoidBottom', subStyle.avoid_bottom);
    setChecked('setSubShowSource', subStyle.show_source !== false);

    ($('setSubBgColor') as HTMLInputElement).value = subRgbToHex(subStyle.bg_r ?? 0, subStyle.bg_g ?? 0, subStyle.bg_b ?? 0);
    ($('setSubGradColor') as HTMLInputElement).value = subRgbToHex(subStyle.grad_r ?? 1, subStyle.grad_g ?? 0.72, subStyle.grad_b ?? 0.78);
    ($('setSubBorderColor') as HTMLInputElement).value = subRgbToHex(subStyle.border_r ?? 1, subStyle.border_g ?? 0.56, subStyle.border_b ?? 0.72);
    ($('setSubTextColor') as HTMLInputElement).value = subRgbToHex(subStyle.text_r ?? 1, subStyle.text_g ?? 1, subStyle.text_b ?? 1);
    ($('setSubOutlineColor') as HTMLInputElement).value = subRgbToHex(subStyle.outline_r ?? 0, subStyle.outline_g ?? 0, subStyle.outline_b ?? 0);

    ($('setSubBgAlpha') as HTMLInputElement).value = String(Math.round((subStyle.bg_a ?? 0.72) * 100));
    ($('setSubCorner') as HTMLInputElement).value = String(subStyle.corner ?? 10);
    ($('setSubPadding') as HTMLInputElement).value = String(subStyle.padding ?? 14);
    ($('setSubBorderW') as HTMLInputElement).value = String(subStyle.border_w ?? 1.5);
    ($('setSubFontSize') as HTMLInputElement).value = String(subStyle.font_size ?? 22);
    ($('setSubFontWeight') as HTMLInputElement).value = String(subStyle.font_weight ?? 700);
    ($('setSubOutlineW') as HTMLInputElement).value = String(subStyle.outline_w ?? 1.5);
    ($('setSubShadowOff') as HTMLInputElement).value = String(subStyle.shadow_off ?? 2);
    ($('setSubLineGap') as HTMLInputElement).value = String(subStyle.line_gap ?? 4);
    ($('setSubMaxWidth') as HTMLInputElement).value = String(Math.round((subStyle.max_width ?? 0.9) * 100));
    ($('setSubPosX') as HTMLInputElement).value = String(Math.round((subStyle.pos_x ?? 0.5) * 100));
    ($('setSubPosY') as HTMLInputElement).value = String(Math.round((subStyle.pos_y ?? 0.82) * 100));
    ($('setSubAvoidPx') as HTMLInputElement).value = String(subStyle.avoid_bottom_px ?? 60);

    if (subStyle.font) {
      const sel = $('setSubFontSel') as HTMLSelectElement;
      const opt = Array.from(sel.options).find((o) => o.value === subStyle.font);
      if (opt) sel.value = subStyle.font;
    }

    ($('setSubBgAlphaV')).textContent = ($('setSubBgAlpha') as HTMLInputElement).value + '%';
    ($('setSubCornerV')).textContent = ($('setSubCorner') as HTMLInputElement).value;
    ($('setSubPaddingV')).textContent = ($('setSubPadding') as HTMLInputElement).value;
    ($('setSubBorderWV')).textContent = ($('setSubBorderW') as HTMLInputElement).value;
    ($('setSubFontSizeV')).textContent = ($('setSubFontSize') as HTMLInputElement).value;
    ($('setSubFontWeightV')).textContent = ($('setSubFontWeight') as HTMLInputElement).value;
    ($('setSubOutlineWV')).textContent = ($('setSubOutlineW') as HTMLInputElement).value;
    ($('setSubShadowOffV')).textContent = ($('setSubShadowOff') as HTMLInputElement).value;
    ($('setSubLineGapV')).textContent = ($('setSubLineGap') as HTMLInputElement).value;
    ($('setSubMaxWidthV')).textContent = ($('setSubMaxWidth') as HTMLInputElement).value + '%';
    ($('setSubPosXV')).textContent = ($('setSubPosX') as HTMLInputElement).value + '%';
    ($('setSubPosYV')).textContent = ($('setSubPosY') as HTMLInputElement).value + '%';
    ($('setSubAvoidPxV')).textContent = ($('setSubAvoidPx') as HTMLInputElement).value;
  }

  function subBindControls(): void {
    function bindRadio(groupId: string, set: (v: number) => void): void {
      const g = $(groupId); if (!g) return;
      g.querySelectorAll<HTMLElement>('.opt').forEach((o) => (o.onclick = () => {
        g.querySelectorAll<HTMLElement>('.opt').forEach((x) => x.classList.remove('on'));
        o.classList.add('on');
        set(+o.dataset.v!);
        subPush();
      }));
    }
    bindRadio('setSubBgMode', (v) => (subStyle.bg_mode = v));
    bindRadio('setSubAlign', (v) => (subStyle.align = v));

    ([['setSubGradient', 'gradient'], ['setSubBorder', 'border'],
     ['setSubOutline', 'outline'], ['setSubShadow', 'shadow'],
     ['setSubAvoidBottom', 'avoid_bottom'], ['setSubShowSource', 'show_source']] as const).forEach(([id, key]) => {
      ($(id) as HTMLInputElement).addEventListener('change', () => { (subStyle as Record<string, unknown>)[key] = ($(id) as HTMLInputElement).checked; subPush(); });
    });

    ([['setSubBgColor', ['bg_r', 'bg_g', 'bg_b']], ['setSubGradColor', ['grad_r', 'grad_g', 'grad_b']],
     ['setSubBorderColor', ['border_r', 'border_g', 'border_b']],
     ['setSubTextColor', ['text_r', 'text_g', 'text_b']],
     ['setSubOutlineColor', ['outline_r', 'outline_g', 'outline_b']]] as [string, [string, string, string]][]).forEach(([id, keys]) => {
      ($(id) as HTMLInputElement).addEventListener('input', () => {
        const c = subHexToRgb(($(id) as HTMLInputElement).value);
        (subStyle as Record<string, unknown>)[keys[0]] = c.r;
        (subStyle as Record<string, unknown>)[keys[1]] = c.g;
        (subStyle as Record<string, unknown>)[keys[2]] = c.b;
        subPush();
      });
    });

    function bindRange(id: string, set: (v: number) => void, fmt?: (v: number) => string, isFloat?: boolean): void {
      const el = $(id) as HTMLInputElement;
      const label = $(id + 'V');
      el.addEventListener('input', () => {
        const v = isFloat ? parseFloat(el.value) : parseInt(el.value, 10);
        set(v);
        if (label) label.textContent = fmt ? fmt(v) : String(v);
        subPush();
      });
    }
    bindRange('setSubBgAlpha', (v) => (subStyle.bg_a = v / 100), (v) => v + '%');
    bindRange('setSubCorner', (v) => (subStyle.corner = v));
    bindRange('setSubPadding', (v) => (subStyle.padding = v));
    bindRange('setSubBorderW', (v) => (subStyle.border_w = v), undefined, true);
    bindRange('setSubFontSize', (v) => (subStyle.font_size = v));
    bindRange('setSubFontWeight', (v) => (subStyle.font_weight = v));
    bindRange('setSubOutlineW', (v) => (subStyle.outline_w = v), undefined, true);
    bindRange('setSubShadowOff', (v) => (subStyle.shadow_off = v), undefined, true);
    bindRange('setSubLineGap', (v) => (subStyle.line_gap = v));
    bindRange('setSubMaxWidth', (v) => (subStyle.max_width = v / 100), (v) => v + '%');
    bindRange('setSubPosX', (v) => (subStyle.pos_x = v / 100), (v) => v + '%');
    bindRange('setSubPosY', (v) => (subStyle.pos_y = v / 100), (v) => v + '%');
    bindRange('setSubAvoidPx', (v) => (subStyle.avoid_bottom_px = v));

    ($('setSubFontSel') as HTMLSelectElement).addEventListener('change', () => { subStyle.font = ($('setSubFontSel') as HTMLSelectElement).value; subPush(); });

    // 预设选择 / 命名保存 / 删除（subRenderPresets 定义在 IIFE 顶层）
    ($('setSubPreset') as HTMLSelectElement).addEventListener('change', () => {
      const key = ($('setSubPreset') as HTMLSelectElement).value;
      if (!key || !subPresets[key]) return;
      subApplyStyle(subPresets[key]);
      subPush(true);
      subToast('已应用预设「' + ($('setSubPreset') as HTMLSelectElement).selectedOptions[0].textContent + '」');
    });
    ($('setSubSavePreset')).addEventListener('click', () => {
      const name = ($('setSubPresetName') as HTMLInputElement).value.trim();
      if (!name) { subToast('请输入预设名称'); return; }
      bridge.saveSubtitlePreset(name, JSON.stringify(subStyle), function (r: unknown) {
        let res: { ok?: boolean; msg?: string } = {};
        try { res = JSON.parse(String(r || '{}')) as { ok?: boolean; msg?: string }; } catch (e) { }
        if (res && res.ok) {
          bridge.getSubtitleStylePresets(function (p: unknown) {
            try { subPresets = JSON.parse(String(p || '{}')) as Record<string, SubtitleStyleFields>; } catch (e) { subPresets = {}; }
            subRenderPresets(name);
          });
          ($('setSubPresetName') as HTMLInputElement).value = '';
          subToast('已保存预设「' + name + '」');
        } else {
          subToast((res && res.msg) || '保存预设失败');
        }
      });
    });
    ($('setSubDelPreset')).addEventListener('click', () => {
      const key = ($('setSubPreset') as HTMLSelectElement).value;
      if (!key) { subToast('请先选择要删除的预设'); return; }
      if (SUB_BUILTIN_LABELS[key]) { subToast('内置预设不可删除'); return; }
      bridge.deleteSubtitlePreset(key, function (r: unknown) {
        let res: { ok?: boolean; msg?: string } = {};
        try { res = JSON.parse(String(r || '{}')) as { ok?: boolean; msg?: string }; } catch (e) { }
        if (res && res.ok) {
          bridge.getSubtitleStylePresets(function (p: unknown) {
            try { subPresets = JSON.parse(String(p || '{}')) as Record<string, SubtitleStyleFields>; } catch (e) { subPresets = {}; }
            subRenderPresets('');
          });
          subToast('已删除预设「' + key + '」');
        } else {
          subToast((res && res.msg) || '删除预设失败');
        }
      });
    });
    ($('setSubLoad')).addEventListener('click', () => {
      bridge.getSubtitleStyle(function (s: unknown) {
        try { subApplyStyle(JSON.parse(String(s || '{}')) as SubtitleStyleFields); } catch (e) { }
        subToast('已加载已保存配置');
      });
    });

    ($('setSubPreview')).addEventListener('click', () => { bridge.previewSubtitle(); subToast('已发送预览字幕'); });
    ($('setSubHide')).addEventListener('click', () => { bridge.hideSubtitle(); subToast('字幕已隐藏'); });
    ($('setSubDrag')).addEventListener('click', () => {
      subDragArmed = !subDragArmed;
      bridge.setSubtitleDrag(subDragArmed);
      ($('setSubDrag')).textContent = subDragArmed ? '拖拽中…（松开即存）' : '拖拽调整字幕';
      if (subDragArmed) subToast('拖拽字幕到目标位置，松开后自动保存');
    });
  }

  function subLoadConfig(): void {
    if (!bridge) return;
    Promise.all([
      new Promise((res: (v: string) => void) => bridge.getSubtitleStyle((s: unknown) => res(String(s || '{}')))),
      new Promise((res: (v: string) => void) => bridge.getSubtitleStylePresets((s: unknown) => res(String(s || '{}')))),
    ]).then(([s, p]) => {
      try { subApplyStyle(JSON.parse(s) as SubtitleStyleFields); } catch (e) { }
      try { subPresets = JSON.parse(p) as Record<string, SubtitleStyleFields>; } catch (e) { subPresets = {}; }
      subRenderPresets('');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    subBindControls();
  });
  window.SubtitleStyle = { load: subLoadConfig };
})();