#include "pipe_server.h"

namespace {
std::wstring Utf8ToWide(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(n, L'\0');
    if (n) MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}
}

DWORD WINAPI PipeServer::threadProc(LPVOID param) {
    static_cast<PipeServer*>(param)->loop();
    return 0;
}

PipeServer::PipeServer(std::string pipeName, MessageHandler handler)
    : m_pipeName(std::move(pipeName)), m_handler(std::move(handler)) {
    InitializeCriticalSection(&m_writeCs);
}

PipeServer::~PipeServer() {
    stop();
    DeleteCriticalSection(&m_writeCs);
}

bool PipeServer::start() {
    if (m_thread) return true;
    m_stopping = false;
    m_thread = CreateThread(nullptr, 0, threadProc, this, 0, nullptr);
    return m_thread != nullptr;
}

void PipeServer::stop() {
    m_stopping = true;
    EnterCriticalSection(&m_writeCs);
    if (m_pipe) CancelIoEx(m_pipe, nullptr);
    LeaveCriticalSection(&m_writeCs);
    if (m_thread) {
        WaitForSingleObject(m_thread, INFINITE);
        CloseHandle(m_thread);
        m_thread = nullptr;
    }
}

void PipeServer::loop() {
    const auto name = L"\\\\.\\pipe\\" + Utf8ToWide(m_pipeName);
    while (!m_stopping) {
        HANDLE pipe = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT, 1, 65536, 65536, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) { Sleep(50); continue; }
        EnterCriticalSection(&m_writeCs);
        m_pipe = pipe;
        LeaveCriticalSection(&m_writeCs);
        OVERLAPPED ov = {};
        ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        // 不在取消后释放 OVERLAPPED/缓冲区，必须等内核完成此次操作。
        auto finish = [&](DWORD& bytes) {
            while (!m_stopping && WaitForSingleObject(ov.hEvent, 50) == WAIT_TIMEOUT) {}
            if (m_stopping) CancelIoEx(pipe, &ov);
            return GetOverlappedResult(pipe, &ov, &bytes, TRUE) != FALSE;
        };
        DWORD bytes = 0;
        bool connected = false;
        if (ov.hEvent && !m_stopping) {
            connected = ConnectNamedPipe(pipe, &ov) != FALSE;
            if (!connected) {
                const auto error = GetLastError();
                connected = error == ERROR_PIPE_CONNECTED || (error == ERROR_IO_PENDING && finish(bytes));
            }
        }
        if (connected && !m_stopping) {
            EnterCriticalSection(&m_writeCs);
            m_clientPipe = pipe;
            LeaveCriticalSection(&m_writeCs);
            char buffer[65536];
            while (!m_stopping) {
                ResetEvent(ov.hEvent);
                bytes = 0;
                bool ok = ReadFile(pipe, buffer, sizeof(buffer), &bytes, &ov) != FALSE;
                if (!ok && GetLastError() == ERROR_IO_PENDING) ok = finish(bytes);
                if (!ok || !bytes || m_stopping) break;
                if (m_handler) m_handler(std::string(buffer, bytes));
            }
        }
        EnterCriticalSection(&m_writeCs);
        m_clientPipe = nullptr;
        m_pipe = nullptr;
        LeaveCriticalSection(&m_writeCs);
        CancelIoEx(pipe, nullptr);
        if (ov.hEvent) CloseHandle(ov.hEvent);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
        if (connected && !m_stopping && m_onDisconnect) m_onDisconnect();
    }
}

bool PipeServer::sendToClient(const std::string& message) {
    EnterCriticalSection(&m_writeCs);
    bool ok = false;
    if (m_clientPipe && !m_stopping) {
        OVERLAPPED ov = {};
        ov.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        DWORD written = 0;
        if (ov.hEvent) {
            ok = WriteFile(m_clientPipe, message.data(), static_cast<DWORD>(message.size()), &written, &ov) != FALSE;
            if (!ok && GetLastError() == ERROR_IO_PENDING) {
                const auto deadline = GetTickCount64() + 2000;
                while (!m_stopping && GetTickCount64() < deadline &&
                       WaitForSingleObject(ov.hEvent, 50) == WAIT_TIMEOUT) {}
                if (m_stopping || GetTickCount64() >= deadline) CancelIoEx(m_clientPipe, &ov);
                ok = GetOverlappedResult(m_clientPipe, &ov, &written, TRUE) != FALSE;
            }
            ok = ok && written == message.size();
            CloseHandle(ov.hEvent);
        }
    }
    LeaveCriticalSection(&m_writeCs);
    return ok;
}
