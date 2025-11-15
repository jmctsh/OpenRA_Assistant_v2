import threading
import time
import json
from typing import Optional, Dict, Any, List

from .api_client import GameAPIClient, TargetsQueryParam, Location


class BrigadeRunner:
    def __init__(self, ai_hq):
        self.ai_hq = ai_hq
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 5.0
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="BrigadeRunner", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def set_task(self, brigade_name: str, task: Optional[Dict[str, Any]]):
        with self._lock:
            if task:
                t = dict(task)
                self._tasks[brigade_name] = t
                pass
            else:
                self._tasks.pop(brigade_name, None)
        try:
            print(f"[DEBUG][BrigadeRunner] set_task {brigade_name}: {json.dumps(task, ensure_ascii=False) if task else 'clear'}")
        except Exception:
            pass

    def set_tasks(self, tasks_map: Dict[str, Any]):
        try:
            for key, task in (tasks_map or {}).items():
                target_name = None
                target_code = None
                for b in getattr(self.ai_hq, 'brigades', []) or []:
                    n = getattr(b, 'name', '')
                    c = getattr(b, 'code', '')
                    if key == n or key == c:
                        target_name = n
                        target_code = c or n
                        break
                if not target_name:
                    continue
                params = {}
                raw = ''
                if isinstance(task, dict):
                    params = task.get('params') or {}
                    raw = str(task.get('task') or task.get('name') or '').strip()
                elif task is not None:
                    raw = str(task).strip()
                try:
                    print(f"[LLM_JSON][SecretaryTask] {json.dumps({'role': 'brigade', 'target': target_code, 'text': raw, 'params': params}, ensure_ascii=False)}")
                except Exception:
                    pass
                try:
                    self.set_task(target_name, {"mission": raw, "mission_raw": raw, "params": params, "source": "secretary"})
                except Exception:
                    pass
                try:
                    cp = getattr(self.ai_hq, 'command_parser', None)
                    if cp:
                        d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                        d[target_name] = raw
                        setattr(cp, '_brigade_task_texts', d)
                except Exception:
                    pass
        except Exception:
            pass

    def clear_task(self, brigade_name: str):
        with self._lock:
            self._tasks.pop(brigade_name, None)
        try:
            cp = getattr(self.ai_hq, 'command_parser', None)
            if cp:
                d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                d[brigade_name] = "自主决策中"
                setattr(cp, '_brigade_task_texts', d)
        except Exception:
            pass

    def _compute_company_centers(self, company_units: Dict[str, List[int]]) -> Dict[str, Dict[str, int]]:
        centers: Dict[str, Dict[str, int]] = {}
        try:
            api = self.ai_hq.api
            for cname, ids in company_units.items():
                actors = api.query_actor(TargetsQueryParam(actorId=ids)) if ids else []
                coords = [(a.position.x, a.position.y) for a in actors if getattr(a, 'position', None)]
                if not coords:
                    continue
                xs = sorted([x for x, _ in coords]); ys = sorted([y for _, y in coords])
                mx = xs[len(xs)//2]; my = ys[len(ys)//2]
                close = [(x, y) for (x, y) in coords if abs(x - mx) + abs(y - my) <= 10]
                if close:
                    ax = sum(x for x, _ in close) // len(close)
                    ay = sum(y for _, y in close) // len(close)
                    centers[cname] = {"x": ax, "y": ay}
                else:
                    centers[cname] = {"x": mx, "y": my}
        except Exception:
            pass
        return centers

    def _do_patrol(self, company_units: Dict[str, List[int]], company: str, center: Dict[str, int], radius: int = 12):
        try:
            ids = company_units.get(company) or []
            if not ids:
                return
            actors = self.ai_hq.api.query_actor(TargetsQueryParam(actorId=ids))
            cx, cy = int(center.get("x", 0)), int(center.get("y", 0))
            import math
            points = 4
            path = []
            for i in range(points):
                ang = i * (2 * math.pi / points)
                x = cx + int(radius * math.cos(ang))
                y = cy + int(radius * math.sin(ang))
                path.append({"x": x, "y": y})
            segment = path
            repeated_path: List[Dict[str, int]] = []
            for _ in range(10):
                repeated_path.extend(segment)
            if segment:
                repeated_path.append(segment[0])
            self.ai_hq.api.move_units_by_path(actors, repeated_path, False)
        except Exception:
            pass

    def _loop(self):
        while self._running:
            try:
                snap = self.ai_hq.staff.snapshot()
                try:
                    self.ai_hq._update_brigade_zones(snap)
                except Exception:
                    pass
                enemies = snap.get("enemies", [])
                for b in self.ai_hq.brigades:
                    name = getattr(b, 'name', '')
                    if not self.ai_hq.company.has_companies(name):
                        try:
                            with self._lock:
                                self._tasks.pop(name, None)
                        except Exception:
                            pass
                        try:
                            cp = getattr(self.ai_hq, 'command_parser', None)
                            if cp:
                                d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                                d[name] = "休眠中"
                                setattr(cp, '_brigade_task_texts', d)
                        except Exception:
                            pass
                        continue
                    with self._lock:
                        tm = self._tasks.get(name) or {}
                    allowed_companies = self.ai_hq.company.get_company_names_for_brigade(name)
                    company_units = {}
                    for cname in allowed_companies:
                        comp = b.companies.get(cname)
                        company_units[cname] = list(getattr(comp, 'unit_ids', []) or []) if comp else []
                    centers = self._compute_company_centers(company_units)
                    mission = None
                    with self._lock:
                        mission = (self._tasks.get(name) or {}).get("mission") or None
                    bc = getattr(b, 'center', None)
                    brigade_center = {"x": int(bc.get("x")), "y": int(bc.get("y"))} if isinstance(bc, dict) else {"x": 0, "y": 0}
                    zone = {"enemies": enemies, "companies": allowed_companies, "company_units": company_units, "company_centers": centers, "brigade_center": brigade_center}
                    try:
                        print(f"[INJECT] company_centers={json.dumps(centers, ensure_ascii=False)}")
                    except Exception:
                        pass
                    try:
                        print(f"[INJECT] brigade_center={name}:{json.dumps(brigade_center, ensure_ascii=False)}")
                    except Exception:
                        pass
                    try:
                        cp = getattr(self.ai_hq, 'command_parser', None)
                        mc = getattr(cp, 'map_cache', {}) if cp else {}
                        eb = snap.get("enemy_base") or mc.get('last_enemy_base') or mc.get('estimated_enemy_base')
                        if (not eb) and cp and hasattr(cp, '_estimate_enemy_base_location'):
                            cp._estimate_enemy_base_location()
                            mc = getattr(cp, 'map_cache', mc)
                            eb = mc.get('last_enemy_base') or mc.get('estimated_enemy_base')
                        zone["enemy_base"] = eb
                        zone["enemy_base_observed"] = bool(mc.get('enemy_base_real_observed'))
                        sp = mc.get('special_points') or {}
                        if (not sp) and cp and hasattr(cp, '_auto_calculate_map_info'):
                            cp._auto_calculate_map_info()
                            mc = getattr(cp, 'map_cache', mc)
                            sp = mc.get('special_points') or {}
                        zone["map_points"] = sp
                        try:
                            print(f"[INJECT] special_points={json.dumps(sp, ensure_ascii=False)}")
                        except Exception:
                            pass
                        try:
                            if eb:
                                print(f"[INJECT] enemy_base={json.dumps(eb, ensure_ascii=False)}")
                        except Exception:
                            pass
                    except Exception:
                        pass
                    plan = self.ai_hq.llm_brigade.plan_dispatch(zone, mission or "engage_nearby", allowed_companies)
                    try:
                        print(f"[LLM_JSON][Brigade] {json.dumps(plan, ensure_ascii=False)}")
                    except Exception:
                        try:
                            print(f"[LLM_JSON][Brigade] {str(plan)}")
                        except Exception:
                            pass
                    dispatch = plan.get("dispatch") or []
                    tools = plan.get("tools") or []
                    pass
                    # 兼容 company_code：转换为名称
                    try:
                        resolved_dispatch = []
                        for d in dispatch:
                            cname = str(d.get("company") or "").strip()
                            ccode = str(d.get("company_code") or "").strip()
                            if not cname and ccode:
                                name_by_code = self.ai_hq.company.get_company_name_by_code(ccode)
                                if name_by_code:
                                    d = dict(d)
                                    d["company"] = name_by_code
                            resolved_dispatch.append(d)
                    except Exception:
                        resolved_dispatch = dispatch
                    try:
                        for d in resolved_dispatch:
                            cname = str(d.get("company") or "")
                            loc = d.get("location") or {}
                            if cname and loc and (str((self._tasks.get(name) or {}).get("mission") or "") != "patrol_base"):
                                self.ai_hq.company_attack_runner.set_task(cname, loc)
                    except Exception:
                        pass
                    for t in tools:
                        if not isinstance(t, dict):
                            continue
                        op = str(t.get("op") or "")
                        if op == "relocate":
                            try:
                                tc = str(t.get("company_code") or "").strip()
                                tn = str(t.get("company") or "").strip()
                                if (not tn) and tc:
                                    by_code = self.ai_hq.company.get_company_name_by_code(tc)
                                    if by_code:
                                        tn = by_code
                                loc = t.get("location") or {}
                                mx = int(loc.get("x", 0)); my = int(loc.get("y", 0))
                                ids = list(company_units.get(tn) or [])
                                if ids and isinstance(mx, int) and isinstance(my, int):
                                    actors = self.ai_hq.api.query_actor(TargetsQueryParam(actorId=ids))
                                    mode = str(t.get("mode") or "").lower()
                                    am = (mode == "attack")
                                    asm = (mode == "assault")
                                    self.ai_hq.api.move_units_by_location(actors, Location(mx, my), am, asm)
                            except Exception:
                                pass
                        elif op == "complete_task":
                            with self._lock:
                                self._tasks.pop(name, None)
                            try:
                                cp = getattr(self.ai_hq, 'command_parser', None)
                                if cp:
                                    d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                                    d[name] = "自主决策中"
                                    setattr(cp, '_brigade_task_texts', d)
                            except Exception:
                                pass
                    try:
                        meta = plan.get("meta") or {}
                        if bool(meta.get("task_complete")):
                            raw = str(((self._tasks.get(name) or {}).get("mission_raw") or mission or "")).strip()
                            standby_words = ["待命", "驻守", "守卫", "巡逻", "集结"]
                            if any(w for w in standby_words if w in raw):
                                pass
                            else:
                                with self._lock:
                                    self._tasks.pop(name, None)
                                try:
                                    cp = getattr(self.ai_hq, 'command_parser', None)
                                    if cp:
                                        d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                                        d[name] = "自主决策中"
                                        setattr(cp, '_brigade_task_texts', d)
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(self._interval)
