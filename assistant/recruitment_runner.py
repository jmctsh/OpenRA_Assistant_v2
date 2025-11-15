import threading
import time
from typing import Optional, Dict, Any, List


class RecruitmentRunner:
    def __init__(self, ai_hq):
        self.ai_hq = ai_hq
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 5.0
        self._task: Optional[Dict[str, Any]] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="RecruitmentRunner", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def set_task(self, task: Optional[Any]):
        self._task = task

    def _loop(self):
        while self._running:
            try:
                snap = self.ai_hq.staff.snapshot()
                t = self._task
                task_text = ''
                if isinstance(t, dict):
                    task_text = str(t.get('desc') or t.get('task') or t.get('name') or '')
                elif t is not None:
                    task_text = str(t)
                if not task_text:
                    task_text = '自主决策中' if self._running else '待命中'
                try:
                    cp = getattr(self.ai_hq, 'command_parser', None)
                    if cp:
                        setattr(cp, '_recruitment_task_text', task_text)
                except Exception:
                    pass
                try:
                    setattr(self.ai_hq, "_last_allies", snap.get("allies", []) or [])
                except Exception:
                    pass
                brigades_info: List[Dict[str, Any]] = []
                for b in self.ai_hq.brigades:
                    brigades_info.append({"name": getattr(b, 'name', ''), "code": getattr(b, 'code', ''), "bounds": {"x0": b.bounds[0], "y0": b.bounds[1], "x1": b.bounds[2], "y1": b.bounds[3]}})
                pass
                self.ai_hq.recruit.plan_and_apply(snap, brigades_info, task=task_text)
                try:
                    for b in self.ai_hq.brigades:
                        comps = self.ai_hq.company.get_companies_for_brigade(getattr(b, 'name', ''))
                        b.assign_companies(comps)
                except Exception:
                    pass
                pass
            except Exception:
                pass
            time.sleep(self._interval)
