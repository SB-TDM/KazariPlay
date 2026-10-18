"""应用内更新用例：检查、探测、下载、跳过。"""
import sys

from utils.infra.logger import get_logger
from utils.update.updater import is_prerelease
from version import VERSION

logger = get_logger()


class UpdateService:
    def __init__(self, version: str = VERSION):
        self.version = version

    def state(self, updater) -> dict:
        try:
            return updater.state()
        except Exception as e:
            logger.error("getUpdateState 失败: %s", e)
            return {"state": "failed", "error": str(e)}

    def check(self, updater, force: bool = False) -> dict:
        try:
            if not getattr(sys, "frozen", False):
                return {"state": "unsupported",
                        "reason": "源码运行模式；请使用发布包获得自动更新"}
            if not bool(force) and is_prerelease(self.version):
                return {"state": "auto_disabled",
                        "reason": "预发布版本默认不自动检查更新"}
            return updater.check(force=bool(force))
        except Exception as e:
            logger.error("checkUpdate 失败: %s", e)
            return {"state": "failed", "error": str(e)}

    def probe_ready(self, updater, data_dir: str) -> dict:
        try:
            if not getattr(sys, "frozen", False):
                return {"state": "idle"}
            from utils.update import update_apply
            if update_apply.has_pending_update_state(data_dir):
                return {"state": "idle"}
            return updater.probe_ready()
        except Exception as e:
            logger.warning("probeReadyUpdate 失败: %s", e)
            return {"state": "idle"}

    def download(self, updater) -> dict:
        try:
            return {"ok": updater.download()}
        except Exception as e:
            logger.error("downloadUpdate 失败: %s", e)
            return {"ok": False, "msg": str(e)}

    def skip(self, updater) -> dict:
        try:
            return updater.skip_current()
        except Exception as e:
            logger.error("skipUpdate 失败: %s", e)
            return {"state": "failed", "error": str(e)}

    def frontend_ready(self, data_dir: str) -> str:
        try:
            from utils.update import update_apply
            return update_apply.mark_startup_success(data_dir) or ""
        except Exception as e:
            logger.warning("前端就绪确认失败: %s", e)
            return ""
