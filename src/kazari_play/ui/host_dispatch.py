"""WinHost 到现有 WebBridge 的业务调用边界。"""
from __future__ import annotations

import inspect
from typing import Any


HOST_LOCAL_METHODS = frozenset({
    "windowMinimize",
    "windowToggleMaximize",
    "windowMaximize",
    "windowRestore",
    "windowClose",
    "windowStartDrag",
    "windowMoveDrag",
    "windowEndDrag",
    "windowResizeStart",
    "windowResize",
})

HOST_INTERNAL_METHODS = frozenset({
    "bind_window",
    "refresh",
    "refresh_delta",
    "notify",
    "reloadCovers",
    "reloadCover",
    "cleanup_unused_covers",
    "set_update_notice",
})

HOST_DISPATCH_METHODS = frozenset({
    "getGames",
    "getGame",
    "getCoverUrl",
    "getCover",
    "getTags",
    "getCategories",
    "getConfig",
    "saveConfigs",
    "resetConfig",
    "setTheme",
    "getConfigPath",
    "toggleFav",
    "launch",
    "openFolder",
    "deleteGame",
    "saveGame",
    "addTag",
    "deleteTag",
    "setGameTags",
    "addCategory",
    "deleteCategory",
    "setGameCategory",
    "batchAddTag",
    "batchRemoveTag",
    "batchMoveCategory",
    "batchDelete",
    "previewRelocate",
    "applyRelocate",
    "getCollectionsTree",
    "createCollection",
    "updateCollection",
    "deleteCollection",
    "reorderCollection",
    "addGamesToCollection",
    "removeGamesFromCollection",
    "setGameCollections",
    "setCollectionGames",
    "getGamesInCollection",
    "moveGameInCollection",
    "batchMoveToCollection",
    "batchRemoveFromCollection",
    "scanFolder",
    "cancelScan",
    "cancelMatch",
    "getBatchProgress",
    "selectExe",
    "matchVndb",
    "matchVndbBatch",
    "getUnmatchedInfo",
    "mergeGames",
    "dismissUnmatched",
    "retryFailedMatches",
    "setRating",
    "getRunning",
    "updateFrontendReady",
    "getUpdateState",
    "checkUpdate",
    "probeReadyUpdate",
    "downloadUpdate",
    "skipUpdate",
    "applyUpdate",
    "openReleasePage",
    "updateScreenshotHotkey",
    "takeScreenshot",
    "takeScreenshotRunning",
    "getScreenshots",
    "getScreenshotThumb",
    "getScreenshotOriginal",
    "deleteScreenshot",
    "renameScreenshot",
    "openScreenshotFolder",
    "copyScreenshotToClipboard",
    "pickCover",
    "setCover",
    "searchMetadata",
    "getGameSources",
    "getMetadataSources",
    "testMetadataConnection",
    "saveMetadataSources",
    "applyCandidate",
})


class DispatchError(Exception):
    """可安全转换为 Host result 的调用错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def dispatch(bridge: Any, method: str, args: list) -> Any:
    """按 allowlist 调用业务方法；不调用窗口或内部生命周期方法。"""
    if not isinstance(method, str) or not method:
        raise DispatchError("unknown_method", "方法名无效")
    if method in HOST_LOCAL_METHODS:
        raise DispatchError("unsupported_window_method", "窗口方法由宿主处理")
    if method.startswith("_") or method in HOST_INTERNAL_METHODS:
        raise DispatchError("unknown_method", "未知方法")
    if method not in HOST_DISPATCH_METHODS:
        raise DispatchError("unknown_method", "未知方法")
    if not isinstance(args, list):
        raise DispatchError("invalid_args", "参数必须是数组")

    fn = getattr(bridge, method, None)
    if not callable(fn):
        raise DispatchError("unknown_method", "未知方法")

    try:
        signature = inspect.signature(fn)
    except (ValueError, TypeError):
        signature = None
    if signature is not None:
        try:
            signature.bind(*args)
        except TypeError as exc:
            raise DispatchError("invalid_args", f"参数不匹配: {exc}") from exc

    try:
        return fn(*args)
    except Exception as exc:
        raise DispatchError("method_failed", f"{type(exc).__name__}: {exc}") from exc
