#pragma once

#include <windows.h>

#include "json.hpp"

nlohmann::json showFileDialog(HWND owner, const nlohmann::json& request);
