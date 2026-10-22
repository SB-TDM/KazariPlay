#include "backend.hpp"

#include <algorithm>
#include <chrono>
#include <vector>

#include "protocol.hpp"

namespace {
constexpr int kPipeBuffer = 65536;

std::wstring pipeName() {
    return L"\\\\.\\pipe\\KazariPlay." + std::to_wstring(GetCurrentProcessId());
}

std::wstring quote(const std::wstring& value) {
    return L"\"" + value + L"\"";
}

bool processAlive(HANDLE process) {
    return process && WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
}
}  // namespace

BackendProcess::~BackendProcess() {
    stop();
}

bool BackendProcess::start(HWND window, const std::wstring& python,
                           const std::wstring& script, const std::wstring& workdir,
                           MessageHandler handler, int timeoutMs) {
    window_ = window;
    handler_ = std::move(handler);
    const std::wstring name = pipeName();
    pipe_ = CreateNamedPipeW(
        name.c_str(),
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        1, kPipeBuffer, kPipeBuffer, 0, nullptr);
    if (pipe_ == INVALID_HANDLE_VALUE) {
        return false;
    }

    std::wstring command = quote(python.empty() ? L"python" : python)
        + L" -B " + quote(script) + L" " + quote(name)
        + L" --host-pid " + std::to_wstring(GetCurrentProcessId());
    std::vector<wchar_t> commandLine(command.begin(), command.end());
    commandLine.push_back(L'\0');

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION info{};
    if (!CreateProcessW(
            nullptr, commandLine.data(), nullptr, nullptr, FALSE,
            CREATE_NO_WINDOW, nullptr, workdir.empty() ? nullptr : workdir.c_str(),
            &startup, &info)) {
        close();
        return false;
    }
    process_ = info.hProcess;
    processId_ = info.dwProcessId;
    CloseHandle(info.hThread);

    if (!connectPipe(timeoutMs) || !readReady(timeoutMs)) {
        stop();
        return false;
    }
    running_ = true;
    reader_ = std::thread(&BackendProcess::readLoop, this);
    return true;
}

bool BackendProcess::connectPipe(int timeoutMs) {
    const DWORD start = GetTickCount();
    while (GetTickCount() - start < static_cast<DWORD>(timeoutMs)) {
        if (ConnectNamedPipe(pipe_, nullptr)) {
            return true;
        }
        if (GetLastError() == ERROR_PIPE_CONNECTED) {
            return true;
        }
        if (!processAlive(process_)) {
            return false;
        }
        Sleep(10);
    }
    return false;
}

bool BackendProcess::readReady(int timeoutMs) {
    nlohmann::json value;
    if (!readFrame(readBuffer_, value, timeoutMs)) {
        return false;
    }
    if (value.value("type", "") != "ready") {
        return false;
    }
    ready_ = value;
    return true;
}

bool BackendProcess::readFrame(std::string& buffer, nlohmann::json& out, int timeoutMs) {
    const auto deadline = std::chrono::steady_clock::now()
        + std::chrono::milliseconds(timeoutMs);
    while (true) {
        if (auto value = host::decodeFrame(buffer)) {
            out = *value;
            return true;
        }
        if (timeoutMs >= 0 && std::chrono::steady_clock::now() >= deadline) {
            return false;
        }
        if (!processAlive(process_) && buffer.empty()) {
            return false;
        }
        DWORD available = 0;
        if (!PeekNamedPipe(pipe_, nullptr, 0, nullptr, &available, nullptr)) {
            return false;
        }
        if (available == 0) {
            Sleep(10);
            continue;
        }
        char data[kPipeBuffer];
        DWORD read = 0;
        if (!ReadFile(pipe_, data, std::min<DWORD>(available, kPipeBuffer), &read, nullptr)
                || read == 0) {
            return false;
        }
        buffer.append(data, read);
    }
}

void BackendProcess::readLoop() {
    while (running_ && !stopping_) {
        nlohmann::json value;
        if (!readFrame(readBuffer_, value, 1000)) {
            if (!processAlive(process_)) {
                break;
            }
            continue;
        }
        if (handler_) {
            handler_(value);
        }
    }
    if (!stopping_ && handler_) {
        handler_(nlohmann::json{{"type", "backend_eof"}});
    }
}

bool BackendProcess::sendCall(int id, const std::string& method,
                              const nlohmann::json& args) {
    return writeFrame({
        {"type", "call"},
        {"id", id},
        {"method", method},
        {"args", args},
    });
}

bool BackendProcess::sendDialogResult(const nlohmann::json& result) {
    return writeFrame(result);
}

bool BackendProcess::sendShutdown() {
    return writeFrame({{"type", "shutdown"}, {"reason", "user"}});
}

bool BackendProcess::writeFrame(const nlohmann::json& value) {
    if (pipe_ == INVALID_HANDLE_VALUE) {
        return false;
    }
    std::string data;
    try {
        data = host::encodeFrame(value);
    } catch (const std::exception&) {
        return false;
    }
    std::lock_guard<std::mutex> guard(writeMutex_);
    std::size_t offset = 0;
    while (offset < data.size()) {
        DWORD written = 0;
        if (!WriteFile(pipe_, data.data() + offset,
                       static_cast<DWORD>(data.size() - offset), &written, nullptr)
                || written == 0) {
            return false;
        }
        offset += written;
    }
    return true;
}

void BackendProcess::stop() {
    if (stopping_.exchange(true)) {
        return;
    }
    running_ = false;
    if (pipe_ != INVALID_HANDLE_VALUE) {
        sendShutdown();
    }
    if (process_ && WaitForSingleObject(process_, 5000) == WAIT_TIMEOUT) {
        TerminateProcess(process_, 1);
        WaitForSingleObject(process_, 2000);
    }
    if (reader_.joinable()) {
        reader_.join();
    }
    close();
}

void BackendProcess::close() {
    if (pipe_ != INVALID_HANDLE_VALUE) {
        CloseHandle(pipe_);
        pipe_ = INVALID_HANDLE_VALUE;
    }
    if (process_) {
        CloseHandle(process_);
        process_ = nullptr;
    }
}
