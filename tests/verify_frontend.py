"""前端模块化完整性校验（临时库，不动真实数据）

验证 main.py 的 _load_html() 组装链路：
1. PARTIALS/SCRIPTS 占位符与外链全部替换，script 块数量与 _JS_MANIFEST 一致
2. JS 中 getElementById / $() 引用的元素 id 全部存在于组装后的 HTML 且不重复
3. 新增 JS/HTML 模块后若忘记登记到 main.py 清单，这里会立刻报错

用法：
    python tests/verify_frontend.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "kazari_play"))

import main  # noqa: E402


def run():
    errors = []
    html = main._load_html()

    # ---------- 1. 占位符 / 外链残留 ----------
    for marker in ("<!-- PARTIALS -->", "<!-- SCRIPTS -->", 'src="js/', 'href="css/'):
        if marker in html:
            errors.append(f"残留标记: {marker}")
    if '<link rel="stylesheet"' in html:
        errors.append("css 未内联")
    if '<div class="logo">☺</div>' in html or '<div class="a-logo">☺</div>' in html:
        errors.append("图标占位符未替换")

    n_open = html.count("<script>")
    n_close = html.count("</script>")
    if n_open != len(main._JS_MANIFEST) or n_close != len(main._JS_MANIFEST):
        errors.append(f"script 块 {n_open}/{n_close} != JS_MANIFEST {len(main._JS_MANIFEST)}")

    # ---------- 2. id 交叉校验（只扫真实 HTML，先剥离内联 JS） ----------
    html_only = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    ids = re.findall(r'id="([^"]+)"', html_only)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append(f"HTML 中重复 id: {dup}")
    id_set = set(ids)

    js_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "kazari_play", "ui", "web_assets", "js")
    refs = set()
    for name in main._JS_MANIFEST:
        src = open(os.path.join(js_dir, name), encoding="utf-8").read()
        refs |= set(re.findall(r"getElementById\('([^']+)'\)", src))
        refs |= set(re.findall(r'getElementById\("([^"]+)"\)', src))
        refs |= set(re.findall(r"\$\('([^']+)'\)", src))  # settings.js 的 $ 助手

    missing = sorted(r for r in refs if r not in id_set)
    if missing:
        errors.append(f"JS 引用但 HTML 缺失的 id: {missing}")

    if errors:
        print("verify_frontend FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print(f"verify_frontend OK: script 块 {n_open} 个, HTML id {len(id_set)} 个, "
          f"JS 引用 {len(refs)} 处全部命中")
    return 0


if __name__ == "__main__":
    sys.exit(run())
