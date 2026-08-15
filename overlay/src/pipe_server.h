#pragma once

#include <windows.h>

#include <functional>
#include <string>

class PipeServer {
public:
    using MessageHandler = std::function<void(const std::string&)>;
    using DisconnectHandler = std::function<void()>;

    explicit PipeServer(std::string pipeName, MessageHandler handler);
    ~PipeServer();

    bool start();
    void stop();

    // 客户端断开回调（管道线程调用，必须快速返回；用于 overlay 自动退出防残留）
    void setOnDisconnect(DisconnectHandler cb) { m_onDisconnect = std::move(cb); }

    // 反向写：C++ -> Python（统一双工长连接，见 pipe_server.cpp）
    // 无连接或断开时返回 false，调用方自行降级（不阻塞）
    bool sendToClient(const std::string& message);

private:
    void loop();
    static DWORD WINAPI threadProc(LPVOID param);

    std::string m_pipeName;
    MessageHandler m_handler;
    DisconnectHandler m_onDisconnect;
    HANDLE m_thread = nullptr;
    volatile bool m_stopping = false;

    HANDLE m_clientPipe = nullptr;      // 当前长连接句柄（pipe 线程持有，UI 线程经锁读写）
    CRITICAL_SECTION m_writeCs;         // 保护 m_clientPipe 与写操作
};
