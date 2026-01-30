import threading
import time
from typing import Optional, Dict, Any, List

from .api_client import GameAPIClient, TargetsQueryParam
from .unit_mapping import UnitMapper
from .llm_roles import LLMCompanyAttack
from .doubao_client import DoubaoClient


class CompanyAttackRunner:
    def __init__(self, ai_hq, client: Optional[DoubaoClient] = None):
        self.ai_hq = ai_hq
        try:
            use_client = client or DoubaoClient()
        except Exception:
            use_client = None
        self.llm = LLMCompanyAttack(use_client)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 5.0
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="CompanyAttackRunner", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def set_task(self, company_name: str, center: Dict[str, int]) -> None:
        with self._lock:
            self._tasks[company_name] = {"center": {"x": int(center.get("x", 0)), "y": int(center.get("y", 0))}}

    def clear_task(self, company_name: str) -> None:
        with self._lock:
            self._tasks.pop(company_name, None)

    def _compute_radius(self, w: int, h: int) -> int:
        try:
            import math
            area = max(1, w * h)
            target_area = area // 4
            r = int(math.sqrt(target_area / math.pi))
            return max(8, r)
        except Exception:
            return max(8, max(w, h) // 4)

    def _gather_zone_units(self, center: Dict[str, int], radius: int, company_name: str) -> Dict[str, List[Dict[str, Any]]]:
        api = self.ai_hq.api
        mapper = self.ai_hq.mapper
        cx = int(center.get("x", 0)); cy = int(center.get("y", 0))
        def in_circle(x: int, y: int) -> bool:
            dx = x - cx; dy = y - cy
            return (dx * dx + dy * dy) <= radius * radius
        enemies: List[Dict[str, Any]] = []
        allies: List[Dict[str, Any]] = []
        try:
            for e in api.query_actor(TargetsQueryParam(faction="敌方")):
                if not e.position:
                    continue
                ex = e.position.x; ey = e.position.y
                if not in_circle(ex, ey):
                    continue
                code = mapper.get_code(e.type) or e.type
                code_str = str(code).lower()
                # 过滤掉出生点标记(mpspawn)和残骸(husk/hask)
                if code_str == "mpspawn" or "husk" in code_str or "hask" in code_str or "残骸" in code_str:
                    continue
                
                # 计算血量百分比 (保留2位小数)
                hp = getattr(e, 'hp', 0) or 0
                max_hp = getattr(e, 'maxHp', 1) or 1
                hp_ratio = round(hp / max_hp, 2) if max_hp > 0 else 0.0
                
                enemies.append({"id": e.actor_id, "type": code, "x": ex, "y": ey, "hp": hp_ratio})
        except Exception:
            enemies = []
        try:
            comp = None
            for b in self.ai_hq.brigades:
                c = b.companies.get(company_name)
                if c:
                    comp = c
                    break
            ids = list(getattr(comp, 'unit_ids', []) or []) if comp else []
            if ids:
                for a in api.query_actor(TargetsQueryParam(actorId=ids)):
                    if not a.position:
                        continue
                    ax = a.position.x; ay = a.position.y
                    if not in_circle(ax, ay):
                        continue
                    code = mapper.get_code(a.type) or a.type
                    code_str = str(code).lower()
                    
                    # 己方过滤：非战斗单位不参与战术分配
                    # e6(工程师), mcv(基地车), harv(矿车), hask/husk(残骸), mpspawn(出生点)
                    if code_str in ("e6", "mcv", "harv", "mpspawn") or "husk" in code_str or "hask" in code_str or "残骸" in code_str:
                        continue
                        
                    # 我方仅需要基础信息，移除血量以减少Token消耗
                    allies.append({"id": a.actor_id, "type": code, "x": ax, "y": ay})
        except Exception:
            allies = []
        return {"enemies": enemies, "allies": allies}

    def _loop(self):
        while self._running:
            try:
                snap = self.ai_hq.staff.snapshot()
                m = snap.get("map") or {}
                w = int(m.get("MapWidth") or m.get("width") or 128)
                h = int(m.get("MapHeight") or m.get("height") or 128)
                radius = self._compute_radius(w, h)
                counters_text = self.llm.get_counters_text() if hasattr(self.llm, 'get_counters_text') else ""
                for cname, t in list(self._tasks.items()):
                    center = t.get("center") or {"x": 0, "y": 0}
                    zone = self._gather_zone_units(center, radius, cname)
                    if not zone.get("enemies") or not zone.get("allies"):
                        self.clear_task(cname)
                        continue
                    plan = self.llm.plan_stream_execute(self.ai_hq.api, counters_text, zone, center, radius)
                    pairs = plan.get("pairs") or []
                    if pairs:
                        try:
                            enhancer = getattr(getattr(self.ai_hq, 'process', None), 'enhancer', None)
                            if enhancer and getattr(enhancer, 'enabled', False):
                                tuples = [(int(p[0]), int(p[1])) for p in pairs if isinstance(p, list) and len(p) == 2]
                                enhancer.enhance_execute(self.ai_hq.api, tuples)
                            else:
                                self.llm.execute_pairs(self.ai_hq.api, pairs)
                        except Exception:
                            self.llm.execute_pairs(self.ai_hq.api, pairs)
            except Exception:
                pass
            time.sleep(self._interval)
