"""Windows PE 版本资源读取（FileDescription / ProductName 等）。"""
import ctypes
import os
from ctypes import wintypes
from typing import Dict


def _version_api():
    if os.name != "nt":
        return None
    return getattr(ctypes, "windll", None) and ctypes.windll.version


def _query(data, sub_block: str) -> str:
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    ver = _version_api()
    if not ver:
        return ""
    if not ver.VerQueryValueW(data, sub_block, ctypes.byref(ptr), ctypes.byref(length)):
        return ""
    if not ptr.value or length.value <= 1:
        return ""
    try:
        return ctypes.wstring_at(ptr.value).strip()
    except Exception:
        return ""


def read_version_info(path: str) -> Dict[str, str]:
    """读取 exe 版本资源；非 Windows、无资源或读取失败时返回空字典。"""
    ver = _version_api()
    if not ver or not path:
        return {}
    ver.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [
        ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL

    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}
    data = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, data):
        return {}

    translations = []
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if ver.VerQueryValueW(data, r"\VarFileInfo\Translation",
                          ctypes.byref(ptr), ctypes.byref(length)):
        if ptr.value and length.value >= 4:
            words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD))
            for i in range(0, length.value // 2, 2):
                translations.append((int(words[i]), int(words[i + 1])))
    if not translations:
        translations = [(0x0409, 0x04B0), (0x0804, 0x04B0), (0x0411, 0x04B0)]

    result = {}
    for field in ("FileDescription", "ProductName", "FileVersion", "CompanyName"):
        value = ""
        for lang, codepage in translations:
            value = _query(
                data, rf"\StringFileInfo\{lang:04x}{codepage:04x}\{field}")
            if value:
                break
        result[field] = value
    return result
