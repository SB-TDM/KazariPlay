#pragma once

#include <windows.h>

#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <atomic>

#include "json.hpp"

class BackendProcess {
public:
    using MessageHandler = std::function<void(const nlohmann::json&)>;

    BackendProcess() = default;
    ~BackendProcess();

    bool start(HWND window, const std::wstring& python,
               const std::wstring& script, const std::wstring& workdir,
               MessageHandler handler, int timeoutMs = 15000);
    bool sendCall(int id, const std::string& method, const nlohmann::json& args);
    bool sendDialogResult(const nlohmann::json& result);
    bool sendShutdown();
    void stop();
    const nlohmann::json& ready() const { return ready_; }
    bool running() const { return running_; }

private:
    bool connectPipe(int timeoutMs);
    bool readReady(int timeoutMs);
    bool readFrame(std::string& buffer, nlohmann::json& out, int timeoutMs);
    void readLoop();
    bool writeFrame(const nlohmann::json& value);
    void close();

    HWND window_ = nullptr;
    HANDLE pipe_ = INVALID_HANDLE_VALUE;
    HANDLE process_ = nullptr;
    DWORD processId_ = 0;
    std::string readBuffer_;
    std::mutex writeMutex_;
    std::thread reader_;
    std::atomic<bool> running_{false};
    std::atomic<bool> stopping_{false};
    MessageHandler handler_;
    nlohmann::json ready_;
};
