#include "dialog.hpp"

#include <shobjidl.h>
#include <wrl/client.h>

#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
std::wstring widen(const std::string& value) {
    if (value.empty()) return {};
    const int length = MultiByteToWideChar(
        CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    std::wstring out(length, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()),
                        out.data(), length);
    return out;
}

nlohmann::json result(int id, bool ok, const std::vector<std::string>& paths) {
    nlohmann::json value = {
        {"type", "dialog_result"},
        {"id", id},
        {"ok", ok},
        {"paths", paths},
    };
    return value;
}
}  // namespace

nlohmann::json showFileDialog(HWND owner, const nlohmann::json& request) {
    const int id = request.value("id", 0);
    const std::string kind = request.value("kind", "");
    if (kind != "folder" && kind != "file") {
        return result(id, false, {});
    }

    ComPtr<IFileOpenDialog> dialog;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(dialog.GetAddressOf())))) {
        return result(id, false, {});
    }
    DWORD options = 0;
    if (FAILED(dialog->GetOptions(&options))) {
        return result(id, false, {});
    }
    options |= FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST;
    if (kind == "folder") options |= FOS_PICKFOLDERS;
    if (request.value("allow_multiple", false)) options |= FOS_ALLOWMULTISELECT;
    if (FAILED(dialog->SetOptions(options))) {
        return result(id, false, {});
    }
    const std::wstring title = widen(request.value("title", ""));
    if (!title.empty()) dialog->SetTitle(title.c_str());

    std::vector<std::wstring> labels;
    std::vector<std::wstring> patterns;
    std::vector<COMDLG_FILTERSPEC> specs;
    const auto filters = request.value("filters", nlohmann::json::array());
    if (filters.is_array()) {
        for (const auto& filter : filters) {
            if (!filter.is_object()) continue;
            labels.push_back(widen(filter.value("label", "")));
            std::wstring pattern;
            const auto values = filter.value("patterns", nlohmann::json::array());
            if (values.is_array()) {
                for (const auto& item : values) {
                    if (!item.is_string()) continue;
                    if (!pattern.empty()) pattern += L";";
                    pattern += widen(item.get<std::string>());
                }
            }
            patterns.push_back(pattern);
        }
    }
    specs.reserve(labels.size());
    for (std::size_t i = 0; i < labels.size(); ++i) {
        specs.push_back(COMDLG_FILTERSPEC{labels[i].c_str(), patterns[i].c_str()});
    }
    if (!specs.empty()) dialog->SetFileTypes(static_cast<UINT>(specs.size()), specs.data());

    const HRESULT shown = dialog->Show(owner);
    if (shown == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
        return result(id, false, {});
    }
    if (FAILED(shown)) {
        return result(id, false, {});
    }

    ComPtr<IShellItemArray> items;
    if (FAILED(dialog->GetResults(items.GetAddressOf()))) {
        return result(id, false, {});
    }
    DWORD count = 0;
    if (FAILED(items->GetCount(&count))) {
        return result(id, false, {});
    }
    std::vector<std::string> paths;
    for (DWORD i = 0; i < count; ++i) {
        ComPtr<IShellItem> item;
        if (FAILED(items->GetItemAt(i, item.GetAddressOf()))) continue;
        PWSTR raw = nullptr;
        if (FAILED(item->GetDisplayName(SIGDN_FILESYSPATH, &raw)) || !raw) continue;
        const int length = WideCharToMultiByte(
            CP_UTF8, 0, raw, -1, nullptr, 0, nullptr, nullptr);
        std::string path(length > 0 ? length : 0, '\0');
        if (length > 1) {
            WideCharToMultiByte(CP_UTF8, 0, raw, -1, path.data(), length, nullptr, nullptr);
            path.resize(length - 1);
        } else {
            path.clear();
        }
        CoTaskMemFree(raw);
        if (!path.empty()) paths.push_back(path);
    }
    return result(id, true, paths);
}
