#pragma once

// ============================================================
// subtitle_style.h — 字幕外观样式（控制面板下发，header-only）
//
// 由 Python 控制面板以 JSON 全量下发（set_subtitle_style），
// SubtitleWindow::applyStyle 解析后应用于渲染与定位。
// 字段命名（snake_case）与前端 control_panel.js 保持一一对应。
// ============================================================

#include <windows.h>

#include <string>

#include "json.hpp"

namespace overlay {

struct SubtitleStyle {
    // ---- 背景 ----
    int bg_mode = 0;        // 0=自适应底板（按文本宽收窄） 1=通栏 2=无底板（仅文字）
    float bg_r = 0.0f, bg_g = 0.0f, bg_b = 0.0f, bg_a = 0.72f;   // 背景色 RGBA
    float corner = 10.0f;   // 圆角 px
    float padding = 14.0f;  // 底板内边距 px
    bool gradient = false;  // 垂直渐变（bg 色 → grad 色）
    float grad_r = 1.0f, grad_g = 0.72f, grad_b = 0.78f, grad_a = 0.9f;
    bool border = false;    // 边框
    float border_w = 1.5f;
    float border_r = 1.0f, border_g = 0.56f, border_b = 0.72f, border_a = 0.7f;

    // ---- 文字 ----
    std::wstring font = L"Microsoft YaHei UI";
    float font_size = 22.0f;   // 译文字号（原文字号 = 0.7 倍）
    int font_weight = 700;     // 100-900
    float text_r = 1.0f, text_g = 1.0f, text_b = 1.0f, text_a = 1.0f;
    bool outline = false;      // 描边（8 向偏移绘制）
    float outline_w = 1.5f;
    float outline_r = 0.0f, outline_g = 0.0f, outline_b = 0.0f, outline_a = 0.8f;
    bool shadow = false;       // 阴影（下方偏移暗色文本）
    float shadow_off = 2.0f;
    float shadow_r = 0.0f, shadow_g = 0.0f, shadow_b = 0.0f, shadow_a = 0.5f;
    int align = 0;             // 0=居中 1=左 2=右
    float line_gap = 4.0f;     // 原文/译文行间距 px
    float max_width = 0.9f;    // 底板最大宽度（占窗口宽比例）
    bool show_source = true;   // 是否显示源语言（原文）字幕行（false = 仅显示译文）

    // ---- 位置（相对游戏窗口百分比）----
    float pos_x = 0.5f;        // 字幕条中心水平位置（0~1）
    float pos_y = 0.82f;       // 字幕条顶部垂直位置（0~1，0=窗口顶）
    bool avoid_bottom = true;  // 底部避让（不与游戏对话框重叠）
    float avoid_bottom_px = 60.0f;

    bool enabled = true;       // 字幕总开关（False = 隐藏且不显示新文本）
};

// 安全取值：值域裁剪，避免越界参数导致绘制异常
inline float ClampF(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// 解析前端下发的样式 JSON（缺省字段保持默认值）
inline SubtitleStyle ParseSubtitleStyle(const std::string& json) {
    SubtitleStyle s;
    try {
        nlohmann::json j = nlohmann::json::parse(json);
        if (!j.is_object()) {
            return s;
        }
        s.bg_mode = j.value("bg_mode", s.bg_mode);
        s.bg_mode = static_cast<int>(ClampF(static_cast<float>(s.bg_mode), 0, 2));
        s.bg_r = ClampF(j.value("bg_r", s.bg_r), 0.f, 1.f);
        s.bg_g = ClampF(j.value("bg_g", s.bg_g), 0.f, 1.f);
        s.bg_b = ClampF(j.value("bg_b", s.bg_b), 0.f, 1.f);
        s.bg_a = ClampF(j.value("bg_a", s.bg_a), 0.f, 1.f);
        s.corner = ClampF(j.value("corner", s.corner), 0.f, 40.f);
        s.padding = ClampF(j.value("padding", s.padding), 0.f, 60.f);
        s.gradient = j.value("gradient", s.gradient);
        s.grad_r = ClampF(j.value("grad_r", s.grad_r), 0.f, 1.f);
        s.grad_g = ClampF(j.value("grad_g", s.grad_g), 0.f, 1.f);
        s.grad_b = ClampF(j.value("grad_b", s.grad_b), 0.f, 1.f);
        s.grad_a = ClampF(j.value("grad_a", s.grad_a), 0.f, 1.f);
        s.border = j.value("border", s.border);
        s.border_w = ClampF(j.value("border_w", s.border_w), 0.f, 12.f);
        s.border_r = ClampF(j.value("border_r", s.border_r), 0.f, 1.f);
        s.border_g = ClampF(j.value("border_g", s.border_g), 0.f, 1.f);
        s.border_b = ClampF(j.value("border_b", s.border_b), 0.f, 1.f);
        s.border_a = ClampF(j.value("border_a", s.border_a), 0.f, 1.f);

        std::string font = j.value("font", "");
        if (!font.empty()) {
            int n = MultiByteToWideChar(CP_UTF8, 0, font.c_str(),
                                        static_cast<int>(font.size()), nullptr, 0);
            if (n > 0) {
                s.font.resize(static_cast<size_t>(n));
                MultiByteToWideChar(CP_UTF8, 0, font.c_str(),
                                    static_cast<int>(font.size()), &s.font[0], n);
            }
        }
        s.font_size = ClampF(j.value("font_size", s.font_size), 8.f, 80.f);
        s.font_weight = static_cast<int>(ClampF(
            static_cast<float>(j.value("font_weight", s.font_weight)), 100.f, 900.f));
        s.text_r = ClampF(j.value("text_r", s.text_r), 0.f, 1.f);
        s.text_g = ClampF(j.value("text_g", s.text_g), 0.f, 1.f);
        s.text_b = ClampF(j.value("text_b", s.text_b), 0.f, 1.f);
        s.text_a = ClampF(j.value("text_a", s.text_a), 0.f, 1.f);
        s.outline = j.value("outline", s.outline);
        s.outline_w = ClampF(j.value("outline_w", s.outline_w), 0.f, 8.f);
        s.outline_r = ClampF(j.value("outline_r", s.outline_r), 0.f, 1.f);
        s.outline_g = ClampF(j.value("outline_g", s.outline_g), 0.f, 1.f);
        s.outline_b = ClampF(j.value("outline_b", s.outline_b), 0.f, 1.f);
        s.outline_a = ClampF(j.value("outline_a", s.outline_a), 0.f, 1.f);
        s.shadow = j.value("shadow", s.shadow);
        s.shadow_off = ClampF(j.value("shadow_off", s.shadow_off), 0.f, 16.f);
        s.shadow_r = ClampF(j.value("shadow_r", s.shadow_r), 0.f, 1.f);
        s.shadow_g = ClampF(j.value("shadow_g", s.shadow_g), 0.f, 1.f);
        s.shadow_b = ClampF(j.value("shadow_b", s.shadow_b), 0.f, 1.f);
        s.shadow_a = ClampF(j.value("shadow_a", s.shadow_a), 0.f, 1.f);
        s.align = static_cast<int>(ClampF(static_cast<float>(j.value("align", s.align)), 0, 2));
        s.line_gap = ClampF(j.value("line_gap", s.line_gap), 0.f, 40.f);
        s.max_width = ClampF(j.value("max_width", s.max_width), 0.2f, 1.f);
        s.show_source = j.value("show_source", s.show_source);
        s.pos_x = ClampF(j.value("pos_x", s.pos_x), 0.f, 1.f);
        s.pos_y = ClampF(j.value("pos_y", s.pos_y), 0.f, 1.f);
        s.avoid_bottom = j.value("avoid_bottom", s.avoid_bottom);
        s.avoid_bottom_px = ClampF(j.value("avoid_bottom_px", s.avoid_bottom_px), 0.f, 400.f);
        s.enabled = j.value("enabled", s.enabled);
    } catch (...) {
        // JSON 解析失败：保持默认样式
    }
    return s;
}

}  // namespace overlay
