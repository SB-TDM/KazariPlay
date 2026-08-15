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
    : m_pipeName(std::move(pipeName)), m_handler(std::move(handler)) {
    InitializeCriticalSection(&m_writeCs);
}

PipeServer::~PipeServer() {
    stop();
    DeleteCriticalSection(&m_writeCs);
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
    // 打断挂起读，让 loop 尽快退出
    EnterCriticalSection(&m_writeCs);
    if (m_clientPipe) {
        CancelIoEx(m_clientPipe, nullptr);
    }
    LeaveCriticalSection(&m_writeCs);
    // 必须等管道线程退出后再释放 CS/句柄，否则线程会访问已删除的临界区（0xC0000005）
    if (m_thread) {
        WaitForSingleObject(m_thread, 3000);
        CloseHandle(m_thread);
        m_thread = nullptr;
    }
    EnterCriticalSection(&m_writeCs);
    if (m_clientPipe) {
        DisconnectNamedPipe(m_clientPipe);
        CloseHandle(m_clientPipe);
        m_clientPipe = nullptr;
    }
    LeaveCriticalSection(&m_writeCs);
}

void PipeServer::loop() {
    // 统一长连接：唯一客户端是 Python（KazariPlay 主程序）。
    // Python 保持一条双工连接：写命令 + 读回传（stable_text/hook_candidates/hook_error）。
    //
    // ⚠️ 必须用 FILE_FLAG_OVERLAPPED + 重叠 ReadFile：
    //   同步（阻塞）ReadFile 挂起时会阻塞同一句柄上后续的 WriteFile
    //   （sendToClient 由 UI 线程/看门狗线程调用），导致命令与回传互相卡死。
    const std::wstring fullName = L"\\\\.\\pipe\\" + Utf8ToWide(m_pipeName);
    char buf[65536];   // 64KB，扛住自动播放/快进的文本突发（原 4096）
    while (!m_stopping) {
        HANDLE pipe = CreateNamedPipeW(
            fullName.c_str(),
            PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,   // 双向 + 重叠 I/O
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            1,                                           // 单实例即可
            65536, 65536, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            Sleep(500);
            continue;
        }

        // 等待客户端连接（重叠 ConnectNamedPipe）
        OVERLAPPED ovConnect = {};
        ovConnect.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        BOOL connected = ConnectNamedPipe(pipe, &ovConnect);
        if (!connected) {
            DWORD err = GetLastError();
            if (err == ERROR_IO_PENDING) {
                WaitForSingleObject(ovConnect.hEvent, INFINITE);
            } else if (err != ERROR_PIPE_CONNECTED) {
                CloseHandle(ovConnect.hEvent);
                CloseHandle(pipe);
                Sleep(200);
                continue;
            }
        }
        CloseHandle(ovConnect.hEvent);

        // 连接建立即持有句柄：Python 命令与 C++ 回传共用这一条连接
        EnterCriticalSection(&m_writeCs);
        m_clientPipe = pipe;
        LeaveCriticalSection(&m_writeCs);

        // 重叠读循环：同一挂起读反复等待（200ms 轮询以响应 stop/断线），
        // 完成后才重新发起下一次读；禁止在挂起时复用 OVERLAPPED 重发读。
        OVERLAPPED ovRead = {};
        ovRead.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        bool reading = false;
        DWORD read = 0;
        while (!m_stopping) {
            if (!reading) {
                ResetEvent(ovRead.hEvent);
                read = 0;
                BOOL ok = ReadFile(pipe, buf, sizeof(buf) - 1, &read, &ovRead);
                if (!ok) {
                    DWORD err = GetLastError();
                    if (err != ERROR_IO_PENDING) {
                        break;   // 硬错误 → 客户端断开
                    }
                    reading = true;   // 挂起读已发起，等待其完成
                } else if (read == 0) {
                    break;   // 立即完成但无数据 → 断开
                } else {
                    // 立即完成且有数据：直接处理
                    buf[read] = '\0';
                    if (m_handler) {
                        m_handler(std::string(buf, read));
                    }
                    continue;
                }
            }
            // reading == true：等待同一个挂起读完成
            DWORD wait = WaitForSingleObject(ovRead.hEvent, 200);
            if (wait == WAIT_OBJECT_0) {
                reading = false;
                if (!GetOverlappedResult(pipe, &ovRead, &read, FALSE) || read == 0) {
                    break;   // 客户端断开
                }
                buf[read] = '\0';
                if (m_handler) {
                    m_handler(std::string(buf, read));
                }
            } else if (m_stopping) {
                CancelIoEx(pipe, &ovRead);   // 取消挂起读，让 loop 尽快退出
                break;
            }
            // WAIT_TIMEOUT 且未停止：继续等待同一挂起读
        }
        CloseHandle(ovRead.hEvent);

        EnterCriticalSection(&m_writeCs);
        m_clientPipe = nullptr;   // 断开后清空，sendToClient 返回 false
        LeaveCriticalSection(&m_writeCs);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);

        // 客户端断开（Python 退出/崩溃/主动 quit）→ 通知上层退出，避免进程残留
        if (m_onDisconnect) {
            m_onDisconnect();
        }
        // 正常情况下发送过 quit 消息后也会走到这里，此时 m_stopping 已置位，
        // 但显式 break 保证不再进入下一轮等待连接
        if (m_stopping) {
            break;
        }
    }
}

bool PipeServer::sendToClient(const std::string& message) {
    EnterCriticalSection(&m_writeCs);
    if (!m_clientPipe) {
        LeaveCriticalSection(&m_writeCs);
        return false;
    }
    DWORD written = 0;
    // 重叠句柄上同步写：数据写入管道缓冲即返回；不要 FlushFileBuffers——
    // 它会阻塞到对端读取，客户端未及时读时会卡死本线程（管道线程/UI 线程）。
    BOOL ok = WriteFile(m_clientPipe, message.c_str(),
                        static_cast<DWORD>(message.size()), &written, nullptr);
    LeaveCriticalSection(&m_writeCs);
    return ok != 0;
}
