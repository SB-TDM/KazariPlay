#include "filter_chain.h"

#include "filters/control_char.h"
#include "filters/dedup_chars.h"
#include "filters/dedup_lines.h"
#include "filters/dedup_mixed_lines.h"
#include "filters/english_symbol.h"
#include "filters/furigana.h"
#include "filters/html_tag.h"
#include "filters/incremental_dedup.h"
#include "filters/line_trimmer.h"
#include "filters/quote_only.h"
#include "filters/regex_replace.h"
#include "filters/shift_jis.h"
#include "filters/unicode_normalize.h"

#include <algorithm>

namespace overlay {

FilterChain::FilterChain() {
    InitializeCriticalSection(&m_cs);
    registerBuiltins();
}

FilterChain::~FilterChain() {
    DeleteCriticalSection(&m_cs);
}

void FilterChain::registerBuiltins() {
    m_allFilters.push_back(std::make_unique<DedupCharsFilter>());
    m_allFilters.push_back(std::make_unique<DedupLinesFilter>());
    m_allFilters.push_back(std::make_unique<DedupMixedLinesFilter>());
    m_allFilters.push_back(std::make_unique<IncrementalDedupFilter>());
    m_allFilters.push_back(std::make_unique<FuriganaFilter>());
    m_allFilters.push_back(std::make_unique<HtmlTagFilter>());
    m_allFilters.push_back(std::make_unique<ControlCharFilter>());
    m_allFilters.push_back(std::make_unique<ShiftJisFilter>());
    m_allFilters.push_back(std::make_unique<EnglishSymbolFilter>());
    m_allFilters.push_back(std::make_unique<QuoteOnlyFilter>());
    m_allFilters.push_back(std::make_unique<UnicodeNormalizerFilter>());
    m_allFilters.push_back(std::make_unique<LineTrimmerFilter>());
    m_allFilters.push_back(std::make_unique<RegexReplaceFilter>());
    EnterCriticalSection(&m_cs);
    m_enabled.clear();
    LeaveCriticalSection(&m_cs);
}

void FilterChain::configure(const std::vector<FilterConfig>& configs) {
    std::vector<std::pair<int, TextFilter*>> enabled;
    for (const auto& cfg : configs) {
        if (!cfg.enabled) continue;
        for (auto& f : m_allFilters) {
            if (f->id() == cfg.id) {
                enabled.emplace_back(cfg.order, f.get());
                break;
            }
        }
    }
    std::sort(enabled.begin(), enabled.end(),
              [](const auto& a, const auto& b) { return a.first < b.first; });
    EnterCriticalSection(&m_cs);
    m_enabled = std::move(enabled);
    LeaveCriticalSection(&m_cs);
}

std::wstring FilterChain::run(const std::wstring& text) {
    std::wstring result = text;
    std::vector<TextFilter*> enabled;
    EnterCriticalSection(&m_cs);
    enabled.reserve(m_enabled.size());
    for (const auto& [order, filter] : m_enabled) {
        (void)order;
        enabled.push_back(filter);
    }
    LeaveCriticalSection(&m_cs);
    for (auto* filter : enabled) {
        result = filter->apply(result);
        if (result.empty()) {
            return L"";   // 被过滤光
        }
    }
    return result;
}

std::vector<FilterConfig> FilterChain::listAvailable() const {
    std::vector<FilterConfig> out;
    out.reserve(m_allFilters.size());
    EnterCriticalSection(&m_cs);
    for (const auto& f : m_allFilters) {
        FilterConfig cfg;
        cfg.id = f->id();
        cfg.enabled = false;
        cfg.order = 0;
        for (const auto& [order, ef] : m_enabled) {
            if (ef == f.get()) {
                cfg.enabled = true;
                cfg.order = order;
                break;
            }
        }
        out.push_back(std::move(cfg));
    }
    LeaveCriticalSection(&m_cs);
    return out;
}

}  // namespace overlay
