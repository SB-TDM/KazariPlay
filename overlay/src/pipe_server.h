#pragma once

#include <windows.h>

#include <functional>
#include <string>

class PipeServer {
public:
    using MessageHandler = std::function<void(const std::string&)>;

    explicit PipeServer(std::string pipeName, MessageHandler handler);
    ~PipeServer();

    bool start();
    void stop();

private:
    void loop();
    static DWORD WINAPI threadProc(LPVOID param);

    std::string m_pipeName;
    MessageHandler m_handler;
    HANDLE m_thread = nullptr;
    volatile bool m_stopping = false;
};
