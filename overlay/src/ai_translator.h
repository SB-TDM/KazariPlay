#pragma once

#include <windows.h>

#include <atomic>
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

namespace overlay {

// AI 翻译器：WinHTTP 调 OpenAI 兼容 chat/completions（默认 DeepSeek）。
// - 异步队列：翻译不阻塞字幕（先显示原文，翻译完成回调替换）
// - translateSync：同步测试（设置页 test_translation 用）
// - cleanAsync：异步 AI 兜底清洗（过滤器链无法确定的脏文本，见 Phase 3）
class AiTranslator {
public:
    enum class TaskType { Translate, Clean };

    using TranslateCallback = std::function<void(int64_t handle,
                                                 const std::string& original,
                                                 const std::string& translated)>;
    // 清洗完成回调：(handle, original, cleaned)
    using CleanCallback = std::function<void(int64_t handle,
                                             const std::string& original,
                                             const std::string& cleaned)>;

    AiTranslator() = default;
    ~AiTranslator();

    // 配置（StartHook 时由 Python 传入）
    void configure(const std::string& baseUrl, const std::string& apiKey,
                   const std::string& model,
                   const std::string& sourceLang, const std::string& targetLang);

    // 异步翻译：入队，翻译完成回调（不阻塞调用线程）
    void translateAsync(int64_t handle, const std::string& text);

    // 异步 AI 清洗：入队，清洗完成回调（不阻塞调用线程）
    void cleanAsync(int64_t handle, const std::string& text);

    // 同步翻译（设置页 test_translation；返回 true=成功）
    bool translateSync(const std::string& text, std::string& out, std::string& err);

    // 停止 worker 并等待退出
    void shutdown();

    void setCallback(TranslateCallback cb) { m_callback = std::move(cb); }
    void setCleanCallback(CleanCallback cb) { m_cleanCallback = std::move(cb); }

    bool configured() const { return m_configured; }

private:
    struct Task {
        int64_t handle = 0;
        TaskType type = TaskType::Translate;
        std::string text;
    };

    void workerLoop();
    bool doRequest(const std::string& text, TaskType type, std::string& out);

    std::string m_baseUrl;
    std::string m_apiKey;
    std::string m_model;
    std::string m_src;
    std::string m_dst;
    std::atomic<bool> m_configured{false};

    std::deque<Task> m_queue;
    std::mutex m_mutex;
    std::condition_variable m_cv;
    std::thread m_worker;
    std::atomic<bool> m_stop{false};
    TranslateCallback m_callback;
    CleanCallback m_cleanCallback;
};

}  // namespace overlay
