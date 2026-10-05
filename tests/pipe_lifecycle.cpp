#include "pipe_server.h"
#include <chrono>
#include <thread>
#include <stdexcept>
#include <iostream>

int main() {
    for (int i = 0; i < 4; ++i) {
        PipeServer server("KazariPipeStopTest", [](const std::string&) {});
        if (!server.start()) return 1;
        Sleep(50);
        auto start = GetTickCount64();
        server.stop();
        if (GetTickCount64() - start > 2000) return 2;
    }
    PipeServer server("KazariPipeWriteTest", [](const std::string&) {});
    if (!server.start()) return 3;
    HANDLE client = INVALID_HANDLE_VALUE;
    for (int i = 0; i < 40 && client == INVALID_HANDLE_VALUE; ++i) {
        client = CreateFileW(L"\\\\.\\pipe\\KazariPipeWriteTest", GENERIC_READ | GENERIC_WRITE,
                             0, nullptr, OPEN_EXISTING, 0, nullptr);
        Sleep(25);
    }
    if (client == INVALID_HANDLE_VALUE) return 4;
    std::thread writer([&server]() { server.sendToClient(std::string(200000, 'x')); });
    Sleep(100);
    server.stop();
    writer.join();
    CloseHandle(client);
    std::cout << "PIPE LIFECYCLE PASS: unconnected stop, pending read/write stop\n";
}
