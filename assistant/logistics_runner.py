import threading
import time
from typing import Optional, Dict, Any

from .api_client import GameAPIClient
from .unit_mapping import UnitMapper


class LogisticsRunner:
    def __init__(self, ai_hq):
        self.ai_hq = ai_hq
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 5.0
        self._task_directive: Optional[Dict[str, Any]] = None
        self._recruitment_advisory: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._recent_decisions: list = []
        self._display_summary: Optional[str] = None
        

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="LogisticsRunner", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def set_task(self, task_params: Optional[Dict[str, Any]]):
        with self._lock:
            self._task_directive = task_params or None

    def set_task_directive(self, task_params: Optional[Dict[str, Any]]):
        with self._lock:
            self._task_directive = task_params or None

    def clear_task(self):
        with self._lock:
            self._task_directive = None

    def set_advisory(self, advisory: Optional[Dict[str, Any]]):
        with self._lock:
            self._recruitment_advisory = advisory or None

    

    def _loop(self):
        while self._running:
            try:
                bf = self.ai_hq.staff.snapshot()
                with self._lock:
                    directive = self._task_directive
                    advisory = self._recruitment_advisory
                try:
                    cp = getattr(self.ai_hq, 'command_parser', None)
                    if cp:
                        if directive:
                            pass
                        else:
                            setattr(cp, '_logistics_task_text', '自主决策中' if self._running else '待命中')
                except Exception:
                    pass
                pass
                plan = self.ai_hq.logistics.plan(bf, task_directive=directive, recruitment_advisory=advisory, recent_decisions=self._recent_decisions[:])
                pass
                # 执行工具
                result_desc = self.ai_hq.logistics.execute(plan)
                pass
                try:
                    self._display_summary = result_desc or None
                except Exception:
                    pass
                try:
                    tools = plan.get("tools") or []
                    for t in tools:
                        if not isinstance(t, dict):
                            continue
                        item = {
                            "type": str(t.get("type") or ""),
                            "unit": str(t.get("unit") or ""),
                            "quantity": int(t.get("quantity") or 1),
                            "queue": str(t.get("queue") or "")
                        }
                        self._recent_decisions.append(item)
                    if len(self._recent_decisions) > 5:
                        self._recent_decisions = self._recent_decisions[-5:]
                except Exception:
                    pass
                # 任务完成标记
                try:
                    meta = plan.get("meta") or {}
                    if bool(meta.get("task_complete")):
                        with self._lock:
                            self._task_directive = None
                except Exception:
                    pass
            except Exception:
                pass
            # 间隔
            time.sleep(self._interval)
