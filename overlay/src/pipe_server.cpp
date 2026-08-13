#include "pipe_server.h"

#include <windows.h>

#include <string>

namespace {

std::wstring Utf8ToWide(const std::string& s) {
    if (s.empty()) {
        return {};
    }
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    if (n <= 0) {
        return {};
    }
    std::wstring w(static_cast<size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), &w[0], n);
    return w;
}

}  // namespace

DWORD WINAPI PipeServer::threadProc(LPVOID param) {
    auto* self = static_cast<PipeServer*>(param);
    self->loop();
    return 0;
}

PipeServer::PipeServer(std::string pipeName, MessageHandler handler)
    : m_pipeName(std::move(pipeName)), m_handler(std::move(handler)) {}

PipeServer::~PipeServer() {
    stop();
}

bool PipeServer::start() {
    if (m_thread) {
        return true;
    }
    m_stopping = false;
    m_thread = CreateThread(nullptr, 0, threadProc, this, 0, nullptr);
    return m_thread != nullptr;
}

void PipeServer::stop() {
    m_stopping = true;
    if (m_thread) {
        CloseHandle(m_thread);
        m_thread = nullptr;
    }
}

void PipeServer::loop() {
    const std::wstring fullName = L"\\\\.\\pipe\\" + Utf8ToWide(m_pipeName);
    char buf[8192];
    while (!m_stopping) {
        HANDLE pipe = CreateNamedPipeW(fullName.c_str(), PIPE_ACCESS_DUPLEX,
                                       PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                                       PIPE_UNLIMITED_INSTANCES, 4096, 4096, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            Sleep(500);
            continue;
        }
        BOOL connected = ConnectNamedPipe(pipe, nullptr);
        if (!connected && GetLastError() != ERROR_PIPE_CONNECTED) {
            CloseHandle(pipe);
            Sleep(200);
            continue;
        }
        while (!m_stopping) {
            DWORD read = 0;
            BOOL ok = ReadFile(pipe, buf, sizeof(buf) - 1, &read, nullptr);
            if (!ok || read == 0) {
                break;
            }
            buf[read] = '\0';
            if (m_handler) {
                m_handler(std::string(buf, read));
            }
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}
