// ============================================================
// subtitle_style.js — 字幕样式控制面板（设置页「字幕」tab）
// 依赖：core.js（toast/bridge）
// 定义：window.SubtitleStyle（load）/ window.updateSubtitlePos（拖拽回传）
// 被依赖：settings.js（Settings.open / 字幕 tab 激活时调用 SubtitleStyle.load）
// ============================================================

(function () {
  const $ = (id) => document.getElementById(id);

  // ================== 字幕样式（原独立控制面板并入设置页） ==================
  // 控件 id → SubtitleStyle 字段映射；改动实时防抖下发 setSubtitleStyle
  let subStyle = {};
  let subPresets = {};
  let subPushTimer = null;
  let subLastPushed = '';
  let subDragArmed = false;

  function subToast(msg) { toast(msg); }

  function subRgbToHex(r, g, b) {
    const c = (v) => { const n = Math.round(v * 255).toString(16); return n.length < 2 ? '0' + n : n; };
    return '#' + c(r) + c(g) + c(b);
  }
  function subHexToRgb(hex) {
    const h = (hex || '#ffffff').replace('#', '');
    return { r: parseInt(h.slice(0, 2), 16) / 255, g: parseInt(h.slice(2, 4), 16) / 255, b: parseInt(h.slice(4, 6), 16) / 255 };
  }

  // 内置预设标签（仅显示用；用户命名预设直接显示名称）
  const SUB_BUILTIN_LABELS = { original: '原作风格', minimal: '极简无底板', darkglass: '半透黑底' };

  // 预设下拉动态渲染：内置 3 套 + 用户命名预设
  function subRenderPresets(selected) {
    const sel = $('setSubPreset');
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

  function subPush(immediate) {
    const payload = JSON.stringify(subStyle);
    clearTimeout(subPushTimer);
    if (!immediate && payload === subLastPushed) return;
    const send = () => {
      subLastPushed = JSON.stringify(subStyle);
      bridge.setSubtitleStyle(JSON.stringify(subStyle));
    };
    if (immediate) { send(); return; }
    subPushTimer = setTimeout(send, 150);
  }

  // 拖拽结束回传位置 → 更新滑块（web_bridge evaluate_js 调用）
  window.updateSubtitlePos = function (x, y) {
    subStyle.pos_x = Math.max(0, Math.min(1, x));
    subStyle.pos_y = Math.max(0, Math.min(1, y));
    const vx = $('setSubPosX'), vy = $('setSubPosY');
    if (vx) vx.value = Math.round(subStyle.pos_x * 100);
    if (vy) vy.value = Math.round(subStyle.pos_y * 100);
    const lx = $('setSubPosXV'), ly = $('setSubPosYV');
    if (lx) lx.textContent = vx ? vx.value + '%' : '';
    if (ly) ly.textContent = vy ? vy.value + '%' : '';
    subToast('字幕位置已更新');
  };

  function subApplyStyle(s) {
    subStyle = Object.assign(subStyle, s || {});
    const setChecked = (id, v) => { if (typeof v === 'boolean') $(id).checked = v; };

    ['setSubBgMode', 'setSubAlign'].forEach((gid) => {
      const g = $(gid); if (!g) return;
      const v = gid === 'setSubBgMode' ? subStyle.bg_mode : subStyle.align;
      g.querySelectorAll('.opt').forEach((o) => o.classList.toggle('on', +o.dataset.v === v));
    });
    setChecked('setSubGradient', subStyle.gradient);
    setChecked('setSubBorder', subStyle.border);
    setChecked('setSubOutline', subStyle.outline);
    setChecked('setSubShadow', subStyle.shadow);
    setChecked('setSubAvoidBottom', subStyle.avoid_bottom);
    setChecked('setSubShowSource', subStyle.show_source !== false);

    $('setSubBgColor').value = subRgbToHex(subStyle.bg_r ?? 0, subStyle.bg_g ?? 0, subStyle.bg_b ?? 0);
    $('setSubGradColor').value = subRgbToHex(subStyle.grad_r ?? 1, subStyle.grad_g ?? 0.72, subStyle.grad_b ?? 0.78);
    $('setSubBorderColor').value = subRgbToHex(subStyle.border_r ?? 1, subStyle.border_g ?? 0.56, subStyle.border_b ?? 0.72);
    $('setSubTextColor').value = subRgbToHex(subStyle.text_r ?? 1, subStyle.text_g ?? 1, subStyle.text_b ?? 1);
    $('setSubOutlineColor').value = subRgbToHex(subStyle.outline_r ?? 0, subStyle.outline_g ?? 0, subStyle.outline_b ?? 0);

    $('setSubBgAlpha').value = Math.round((subStyle.bg_a ?? 0.72) * 100);
    $('setSubCorner').value = subStyle.corner ?? 10;
    $('setSubPadding').value = subStyle.padding ?? 14;
    $('setSubBorderW').value = subStyle.border_w ?? 1.5;
    $('setSubFontSize').value = subStyle.font_size ?? 22;
    $('setSubFontWeight').value = subStyle.font_weight ?? 700;
    $('setSubOutlineW').value = subStyle.outline_w ?? 1.5;
    $('setSubShadowOff').value = subStyle.shadow_off ?? 2;
    $('setSubLineGap').value = subStyle.line_gap ?? 4;
    $('setSubMaxWidth').value = Math.round((subStyle.max_width ?? 0.9) * 100);
    $('setSubPosX').value = Math.round((subStyle.pos_x ?? 0.5) * 100);
    $('setSubPosY').value = Math.round((subStyle.pos_y ?? 0.82) * 100);
    $('setSubAvoidPx').value = subStyle.avoid_bottom_px ?? 60;

    if (subStyle.font) {
      const opt = Array.from($('setSubFontSel').options).find((o) => o.value === subStyle.font);
      if (opt) $('setSubFontSel').value = subStyle.font;
    }

    $('setSubBgAlphaV').textContent = $('setSubBgAlpha').value + '%';
    $('setSubCornerV').textContent = $('setSubCorner').value;
    $('setSubPaddingV').textContent = $('setSubPadding').value;
    $('setSubBorderWV').textContent = $('setSubBorderW').value;
    $('setSubFontSizeV').textContent = $('setSubFontSize').value;
    $('setSubFontWeightV').textContent = $('setSubFontWeight').value;
    $('setSubOutlineWV').textContent = $('setSubOutlineW').value;
    $('setSubShadowOffV').textContent = $('setSubShadowOff').value;
    $('setSubLineGapV').textContent = $('setSubLineGap').value;
    $('setSubMaxWidthV').textContent = $('setSubMaxWidth').value + '%';
    $('setSubPosXV').textContent = $('setSubPosX').value + '%';
    $('setSubPosYV').textContent = $('setSubPosY').value + '%';
    $('setSubAvoidPxV').textContent = $('setSubAvoidPx').value;
  }

  function subBindControls() {
    function bindRadio(groupId, set) {
      const g = $(groupId); if (!g) return;
      g.querySelectorAll('.opt').forEach((o) => (o.onclick = () => {
        g.querySelectorAll('.opt').forEach((x) => x.classList.remove('on'));
        o.classList.add('on');
        set(+o.dataset.v);
        subPush();
      }));
    }
    bindRadio('setSubBgMode', (v) => (subStyle.bg_mode = v));
    bindRadio('setSubAlign', (v) => (subStyle.align = v));

    [['setSubGradient', 'gradient'], ['setSubBorder', 'border'],
     ['setSubOutline', 'outline'], ['setSubShadow', 'shadow'],
     ['setSubAvoidBottom', 'avoid_bottom'], ['setSubShowSource', 'show_source']].forEach(([id, key]) => {
      $(id).addEventListener('change', () => { subStyle[key] = $(id).checked; subPush(); });
    });

    [['setSubBgColor', ['bg_r', 'bg_g', 'bg_b']], ['setSubGradColor', ['grad_r', 'grad_g', 'grad_b']],
     ['setSubBorderColor', ['border_r', 'border_g', 'border_b']],
     ['setSubTextColor', ['text_r', 'text_g', 'text_b']],
     ['setSubOutlineColor', ['outline_r', 'outline_g', 'outline_b']]].forEach(([id, keys]) => {
      $(id).addEventListener('input', () => {
        const c = subHexToRgb($(id).value);
        subStyle[keys[0]] = c.r; subStyle[keys[1]] = c.g; subStyle[keys[2]] = c.b;
        subPush();
      });
    });

    function bindRange(id, set, fmt, isFloat) {
      const el = $(id);
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
    bindRange('setSubBorderW', (v) => (subStyle.border_w = v), null, true);
    bindRange('setSubFontSize', (v) => (subStyle.font_size = v));
    bindRange('setSubFontWeight', (v) => (subStyle.font_weight = v));
    bindRange('setSubOutlineW', (v) => (subStyle.outline_w = v), null, true);
    bindRange('setSubShadowOff', (v) => (subStyle.shadow_off = v), null, true);
    bindRange('setSubLineGap', (v) => (subStyle.line_gap = v));
    bindRange('setSubMaxWidth', (v) => (subStyle.max_width = v / 100), (v) => v + '%');
    bindRange('setSubPosX', (v) => (subStyle.pos_x = v / 100), (v) => v + '%');
    bindRange('setSubPosY', (v) => (subStyle.pos_y = v / 100), (v) => v + '%');
    bindRange('setSubAvoidPx', (v) => (subStyle.avoid_bottom_px = v));

    $('setSubFontSel').addEventListener('change', () => { subStyle.font = $('setSubFontSel').value; subPush(); });

    // 预设选择 / 命名保存 / 删除（subRenderPresets 定义在 IIFE 顶层）
    $('setSubPreset').addEventListener('change', () => {
      const key = $('setSubPreset').value;
      if (!key || !subPresets[key]) return;
      subApplyStyle(subPresets[key]);
      subPush(true);
      subToast('已应用预设「' + $('setSubPreset').selectedOptions[0].textContent + '」');
    });
    $('setSubSavePreset').addEventListener('click', () => {
      const name = $('setSubPresetName').value.trim();
      if (!name) { subToast('请输入预设名称'); return; }
      bridge.saveSubtitlePreset(name, JSON.stringify(subStyle), function (r) {
        let res = {};
        try { res = JSON.parse(r || '{}'); } catch (e) { }
        if (res && res.ok) {
          bridge.getSubtitleStylePresets(function (p) {
            try { subPresets = JSON.parse(p || '{}'); } catch (e) { subPresets = {}; }
            subRenderPresets(name);
          });
          $('setSubPresetName').value = '';
          subToast('已保存预设「' + name + '」');
        } else {
          subToast((res && res.msg) || '保存预设失败');
        }
      });
    });
    $('setSubDelPreset').addEventListener('click', () => {
      const key = $('setSubPreset').value;
      if (!key) { subToast('请先选择要删除的预设'); return; }
      if (SUB_BUILTIN_LABELS[key]) { subToast('内置预设不可删除'); return; }
      bridge.deleteSubtitlePreset(key, function (r) {
        let res = {};
        try { res = JSON.parse(r || '{}'); } catch (e) { }
        if (res && res.ok) {
          bridge.getSubtitleStylePresets(function (p) {
            try { subPresets = JSON.parse(p || '{}'); } catch (e) { subPresets = {}; }
            subRenderPresets('');
          });
          subToast('已删除预设「' + key + '」');
        } else {
          subToast((res && res.msg) || '删除预设失败');
        }
      });
    });
    $('setSubLoad').addEventListener('click', () => {
      bridge.getSubtitleStyle(function (s) {
        try { subApplyStyle(JSON.parse(s || '{}')); } catch (e) { }
        subToast('已加载已保存配置');
      });
    });

    $('setSubPreview').addEventListener('click', () => { bridge.previewSubtitle(); subToast('已发送预览字幕'); });
    $('setSubHide').addEventListener('click', () => { bridge.hideSubtitle(); subToast('字幕已隐藏'); });
    $('setSubDrag').addEventListener('click', () => {
      subDragArmed = !subDragArmed;
      bridge.setSubtitleDrag(subDragArmed);
      $('setSubDrag').textContent = subDragArmed ? '拖拽中…（松开即存）' : '拖拽调整字幕';
      if (subDragArmed) subToast('拖拽字幕到目标位置，松开后自动保存');
    });
  }

  function subLoadConfig() {
    if (!bridge) return;
    Promise.all([
      new Promise((res) => bridge.getSubtitleStyle((s) => res(s || '{}'))),
      new Promise((res) => bridge.getSubtitleStylePresets((s) => res(s || '{}'))),
    ]).then(([s, p]) => {
      try { subApplyStyle(JSON.parse(s)); } catch (e) { }
      try { subPresets = JSON.parse(p) || {}; } catch (e) { subPresets = {}; }
      subRenderPresets('');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    subBindControls();
  });
  window.SubtitleStyle = { load: subLoadConfig };
})();
