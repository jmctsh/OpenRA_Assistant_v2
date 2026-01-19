from typing import List, Dict, Any, Optional, Tuple
import os
import json
import time
import random
from dataclasses import dataclass

from .api_client import GameAPIClient, TargetsQueryParam, Actor, Location
from .unit_mapping import UnitMapper
from .chief_of_staff import ChiefOfStaff
from .doubao_client import DoubaoClient
from .llm_roles import LLMSecretary, LLMLogistics, LLMBrigadeCommander, LLMRecruitment
from .logistics_runner import LogisticsRunner
from .company_manager import CompanyManager
from .brigade_runner import BrigadeRunner
from .company_attack_runner import CompanyAttackRunner
from .recruitment_runner import RecruitmentRunner


@dataclass
class StrategicTask:
    name: str
    params: Dict[str, Any]


class Secretary:
    def __init__(self, command_parser, client: DoubaoClient):
        self.command_parser = command_parser
        self.llm = LLMSecretary(client)

    def classify(self, text: str) -> Tuple[str, Optional[StrategicTask]]:
        brigades_info = []
        try:
            for b in self.command_parser.ai_hq.brigades:
                brigades_info.append({
                    "name": getattr(b, 'name', ''),
                    "code": getattr(b, 'code', ''),
                    "bounds": {"x0": b.bounds[0], "y0": b.bounds[1], "x1": b.bounds[2], "y1": b.bounds[3]},
                    "center": getattr(b, 'center', None)
                })
        except Exception:
            brigades_info = []
        try:
            battlefield = self.command_parser.ai_hq.staff.snapshot_with_zones(brigades_info)
            # 英文代码拦截：统一 allies/enemies 为英文代码 + 坐标（移除id/hp）
            try:
                mapper = self.command_parser.unit_mapper
                def _to_code(lst):
                    out = []
                    for it in (lst or []):
                        t = it.get("type")
                        x = it.get("x"); y = it.get("y")
                        if x is None or y is None:
                            pos = it.get("position") or {}
                            x = pos.get("x"); y = pos.get("y")
                        if t is None or x is None or y is None:
                            continue
                        code = (mapper.get_code(t) if mapper else t) or t
                        out.append({"type": str(code), "x": int(x), "y": int(y)})
                    return out
                battlefield = dict(battlefield or {})
                battlefield["allies"] = _to_code(battlefield.get("allies") or [])
                battlefield["enemies"] = _to_code(battlefield.get("enemies") or [])
                # 建筑列表统一英文代码
                battlefield["ally_buildings"] = _to_code(battlefield.get("ally_buildings") or [])
                battlefield["enemy_buildings"] = _to_code(battlefield.get("enemy_buildings") or [])
                cp = self.command_parser
                mc = getattr(cp, 'map_cache', {}) if cp else {}
                try:
                    sp = mc.get('special_points') or {}
                    if (not sp) and cp and hasattr(cp, '_auto_calculate_map_info'):
                        cp._auto_calculate_map_info()
                        mc = getattr(cp, 'map_cache', mc)
                        sp = mc.get('special_points') or {}
                    battlefield['special_points'] = sp
                    try:
                        print(f"[INJECT] special_points={json.dumps(sp, ensure_ascii=False)}")
                    except Exception:
                        pass
                except Exception:
                    pass
                a = battlefield.get('ally_base') or mc.get('last_ally_base') or None
                if a:
                    battlefield['ally_base'] = a
                e = battlefield.get('enemy_base') or mc.get('last_enemy_base') or mc.get('estimated_enemy_base') or None
                if not e and cp and hasattr(cp, '_estimate_enemy_base_location'):
                    try:
                        cp._estimate_enemy_base_location()
                        mc = getattr(cp, 'map_cache', mc)
                        e = mc.get('last_enemy_base') or mc.get('estimated_enemy_base') or None
                    except Exception:
                        e = None
                if e:
                    battlefield['enemy_base'] = e
                try:
                    observed = bool((mc or {}).get('enemy_base_real_observed'))
                    battlefield['enemy_base_observed'] = observed
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            battlefield = {}
        try:
            companies = self.command_parser.ai_hq.company.snapshot()
        except Exception:
            companies = {}
        # 连队综述（全局通用，由参谋长提供）：name/count/center
        try:
            overview = self.command_parser.ai_hq.staff.companies_overview(companies)
            battlefield["companies_overview"] = overview
        except Exception:
            pass
        try:
            centers_info = []
            for b in (brigades_info or []):
                c = (b or {}).get("center")
                if isinstance(c, dict) and "x" in c and "y" in c:
                    centers_info.append({"brigade": b.get("code"), "center": {"x": int(c.get("x",0)), "y": int(c.get("y",0))}})
            if centers_info:
                print(f"[INJECT] brigade_centers={json.dumps(centers_info, ensure_ascii=False)}")
        except Exception:
            pass
        res = self.llm.classify(text, context={"brigades_info": brigades_info, "battlefield": battlefield, "companies": companies}) or {}
        try:
            mapper = getattr(self.command_parser, 'unit_mapper', None)
            fixed = []
            for r in list(res.get("routes") or []):
                p = dict(r.get("params") or {})
                if isinstance(p.get("building"), str) and mapper:
                    c = mapper.get_code(p.get("building"))
                    if c:
                        p["building"] = c
                if isinstance(p.get("unit"), str) and mapper:
                    c = mapper.get_code(p.get("unit"))
                    if c:
                        p["unit"] = c
                r = dict(r)
                r["params"] = p
                fixed.append(r)
            if fixed:
                res["routes"] = fixed
        except Exception:
            pass
        try:
            active = set()
            comps = (companies or {}).get("companies") or {}
            for name, meta in comps.items():
                try:
                    units = list(meta.get("units") or [])
                    bcode = str(meta.get("brigade") or "")
                    if units and bcode:
                        active.add(bcode)
                except Exception:
                    pass
            filtered = []
            for r in list(res.get("routes") or []):
                role = str(r.get("role") or "")
                if role != "brigade":
                    filtered.append(r)
                    continue
                p = r.get("params") or {}
                bcode = str(p.get("brigade") or "")
                if bcode and (bcode in active):
                    filtered.append(r)
            res["routes"] = filtered
        except Exception:
            pass
        try:
            setattr(self.command_parser, "_secretary_routes", res.get("routes") or [])
        except Exception:
            pass
        try:
            rep = str(res.get("report") or "").strip()
            if not rep:
                routes_list = list(res.get("routes") or [])
                bc = sum(1 for r in routes_list if str(r.get("role") or "") == "brigade")
                lc = sum(1 for r in routes_list if str(r.get("role") or "") == "logistics")
                rc = sum(1 for r in routes_list if str(r.get("role") or "") == "recruitment")
                parts = []
                if bc:
                    parts.append(f"旅长{bc}条")
                if lc:
                    parts.append("后勤1条" if lc == 1 else f"后勤{lc}条")
                if rc:
                    parts.append("征兵1条" if rc == 1 else f"征兵{rc}条")
                rep = ("已下达：" + "，".join(parts)) if parts else "已完成意图拆解"
            setattr(self.command_parser, "_secretary_report", rep)
        except Exception:
            pass
        try:
            setattr(self.command_parser.ai_hq, "_last_routes", res.get("routes") or [])
        except Exception:
            pass
        routes = res.get("routes") or []
        ai_hq = self.command_parser.ai_hq
        if ai_hq and routes:
            brigade_tasks = {}
            for route in routes:
                role = route.get("role")
                task = route.get("task")
                if not role or not task:
                    continue

                if role == "logistics":
                    if hasattr(ai_hq, 'logistics_runner') and ai_hq.logistics_runner:
                        getattr(ai_hq.logistics_runner, 'set_task_directive', lambda x: None)(task)
                elif role == "recruitment":
                    if hasattr(ai_hq, 'recruitment_runner') and ai_hq.recruitment_runner:
                        getattr(ai_hq.recruitment_runner, 'set_task', lambda x: None)(task)
                elif role.startswith("brigade_"):
                    brigade_tasks[role] = task
            
            if brigade_tasks and hasattr(ai_hq, 'brigade_runner') and ai_hq.brigade_runner:
                getattr(ai_hq.brigade_runner, 'set_tasks', lambda x: None)(brigade_tasks)
        if not routes:
            return "none", None
        t = str((routes or [{}])[0].get("task") or "").strip()
        return "strategic", StrategicTask(name=t, params={})


class LogisticsMinister:
    def __init__(self, api: GameAPIClient, client: DoubaoClient):
        self.api = api
        self.llm = LLMLogistics(client)
    
    def plan(self, battlefield: Dict[str, Any], task_directive: Optional[Dict[str, Any]] = None, recruitment_advisory: Optional[Dict[str, Any]] = None, recent_decisions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return self.llm.plan(battlefield, task_directive, recruitment_advisory, recent_decisions)

    def execute(self, plan: Dict[str, Any]) -> str:
        return self.llm.execute(self.api, plan)

    def plan_and_execute(self, battlefield: Dict[str, Any]) -> str:
        plan = self.llm.plan(battlefield)
        return self.llm.execute(self.api, plan)


class RecruitmentMinister:
    def __init__(self, client: DoubaoClient, company_manager: CompanyManager):
        self.llm = LLMRecruitment(client)
        self.company = company_manager

    def plan_and_apply(self, battlefield: Dict[str, Any], brigades_info: List[Dict[str, Any]], task: Optional[str] = None) -> None:
        allies = battlefield.get("allies", [])
        snap = self.company.snapshot()
        try:
            all_ids = {int(u.get("id")) for u in (allies or []) if isinstance(u.get("id"), int)}
        except Exception:
            all_ids = set()
        comp_ids = set()
        try:
            for name, meta in (snap.get("companies", {}) or {}).items():
                for uid in (meta.get("units") or []):
                    try:
                        comp_ids.add(int(uid))
                    except Exception:
                        pass
        except Exception:
            comp_ids = set()
        unassigned_ids = list(all_ids - comp_ids)
        unassigned_units = []
        try:
            index = {int(u.get("id")): u for u in (allies or []) if isinstance(u.get("id"), int)}
            for uid in unassigned_ids:
                if uid in index:
                    unassigned_units.append(index[uid])
        except Exception:
            unassigned_units = []
        # 为征兵部长提供各连队的兵种组成（英文代码）
        enriched = dict(snap or {})
        try:
            by_id = {int(u.get("id")): u for u in (allies or []) if isinstance(u.get("id"), int)}
            comps = enriched.get("companies") or {}
            for name, meta in list(comps.items()):
                ids = list(meta.get("units") or [])
                compo: Dict[str, int] = {}
                for uid in ids:
                    try:
                        u = by_id.get(int(uid))
                        t = str((u or {}).get("type") or "")
                        if t:
                            compo[t] = compo.get(t, 0) + 1
                    except Exception:
                        pass
                meta["composition"] = compo
        except Exception:
            pass
        # 招募提示词不需要敌方基地、特殊点位或敌方单位信息
        bf_min = {}
        res = self.llm.plan(allies, brigades_info, bf_min, enriched, unassigned_units, task=task) or {}
        summaries: List[str] = []
        assign_pairs = res.get("assign") or []
        if isinstance(assign_pairs, list) and assign_pairs:
            grouped: Dict[str, List[int]] = {}
            try:
                snap_companies = enriched.get("companies") or {}
                bc: Dict[str, int] = {}
                for n, m in snap_companies.items():
                    b = str(m.get("brigade") or "")
                    c = len(m.get("units") or [])
                    if b:
                        bc[b] = bc.get(b, 0) + c
                b1 = int(bc.get("brigade_1", 0))
                b3 = int(bc.get("brigade_3", 0))
                prio: List[str] = []
                if b1 < 20:
                    prio = ["brigade_1"]
                elif b3 < 20:
                    prio = ["brigade_3"]
                else:
                    prio = ["brigade_2", "brigade_4"]
                rr = 0
                def pick_company(bcode: str) -> Optional[str]:
                    names = [f"{bcode}_company1", f"{bcode}_company2", f"{bcode}_company3"]
                    counts = {}
                    for nm in names:
                        meta = snap_companies.get(nm) or {}
                        counts[nm] = len(meta.get("units") or [])
                    if counts.get(names[0], 0) < 10 or counts.get(names[1], 0) < 10:
                        return names[0] if counts.get(names[0], 0) <= counts.get(names[1], 0) else names[1]
                    best = names[0]
                    for nm in names:
                        if counts.get(nm, 0) <= counts.get(best, 0):
                            best = nm
                    return best
                for p in assign_pairs:
                    try:
                        uid = int(p[0])
                        dst = str(p[1])
                    except Exception:
                        continue
                    if uid not in unassigned_ids:
                        continue
                    company = dst or None
                    if company and company.startswith("company_"):
                        company = self.company.get_company_name_by_code(company)
                    target_brigade = None
                    if len(prio) == 1:
                        target_brigade = prio[0]
                    else:
                        target_brigade = prio[rr % len(prio)]
                        rr += 1
                    if company:
                        meta = snap_companies.get(company) or {}
                        bdst = str(meta.get("brigade") or "")
                        if bdst != target_brigade:
                            company = pick_company(target_brigade)
                    else:
                        company = pick_company(target_brigade)
                    if not company:
                        continue
                    grouped.setdefault(company, []).append(uid)
                    if target_brigade:
                        bc[target_brigade] = bc.get(target_brigade, 0) + 1
                for cname, ids in grouped.items():
                    if cname and ids:
                        self.company.assign_units(cname, ids)
                        summaries.append(f"分配 {len(ids)} 至 {cname}")
            except Exception:
                pass
        else:
            tools = res.get("tools") or []
            for t in tools:
                try:
                    op = str(t.get("op") or "")
                    if op == "create_company":
                        pass
                    elif op == "assign_units":
                        company = t.get("company") or self.company.get_company_name_by_code(t.get("company_code"))
                        units = []
                        try:
                            for x in (t.get("units") or []):
                                ux = int(x)
                                if ux in unassigned_ids:
                                    units.append(ux)
                        except Exception:
                            units = []
                        if company and units:
                            self.company.assign_units(company, units)
                            summaries.append(f"分配 {len(units)} 至 {company}")
                    elif op == "reassign_company":
                        pass
                    elif op == "merge_remnants":
                        pass
                    elif op == "dissolve_empty":
                        pass
                except Exception:
                    pass
        try:
            advisory = res.get("advisory") or None
            if advisory and hasattr(self, 'ai_hq_ref') and getattr(self, 'ai_hq_ref', None):
                self.ai_hq_ref.logistics_runner.set_advisory(advisory)
        except Exception:
            pass
        try:
            if hasattr(self, 'ai_hq_ref') and getattr(self, 'ai_hq_ref', None):
                existing = list(getattr(self.ai_hq_ref, '_last_recruit_actions', []) or [])
                existing.extend(summaries)
                if len(existing) > 10:
                    existing = existing[-10:]
                setattr(self.ai_hq_ref, '_last_recruit_actions', existing)
                try:
                    pass
                except Exception:
                    pass
        except Exception:
            pass


class CompanyCommander:
    def __init__(self, api: GameAPIClient, mapper: UnitMapper, name: str):
        self.api = api
        self.mapper = mapper
        self.name = name
        self.unit_ids: List[int] = []

    def set_units(self, ids: List[int]):
        self.unit_ids = list(ids or [])

    def attack_nearest(self, enemies: List[Dict[str, Any]]):
        if not self.unit_ids or not enemies:
            return False
        attackers = self.api.query_actor(TargetsQueryParam(actorId=self.unit_ids))
        target = None
        best = 10**9
        for e in enemies:
            ex = e.get("x"); ey = e.get("y")
            if ex is None or ey is None:
                continue
            for a in attackers:
                if not a.position:
                    continue
                d = abs(a.position.x - ex) + abs(a.position.y - ey)
                if d < best:
                    best = d
                    target = e
        if not target:
            return False
        t_actor = self.api.query_actor(TargetsQueryParam(actorId=[target["id"]]))
        if not t_actor:
            return False
        return self.api.attack_targets(attackers, [t_actor[0]])

    def patrol_center(self, center: Tuple[int, int]):
        if not self.unit_ids:
            return False
        actors = self.api.query_actor(TargetsQueryParam(actorId=self.unit_ids))
        loc = Location(center[0], center[1])
        try:
            self.api.move_units_by_location(actors, loc, attack_move=False, assault_move=False)
            return True
        except Exception:
            return False


class BrigadeCommander:
    def __init__(self, api: GameAPIClient, mapper: UnitMapper, name: str, bounds: Tuple[int, int, int, int], code: str):
        self.api = api
        self.mapper = mapper
        self.name = name
        self.bounds = bounds
        self.code = code
        self.companies: Dict[str, CompanyCommander] = {}
        self._in_fn = None

    def in_bounds(self, x: int, y: int) -> bool:
        if self._in_fn:
            try:
                return bool(self._in_fn(int(x), int(y)))
            except Exception:
                pass
        x0, y0, x1, y1 = self.bounds
        return x >= x0 and x <= x1 and y >= y0 and y <= y1

    def set_zone_fn(self, fn):
        self._in_fn = fn

    def assign_companies(self, companies: Dict[str, List[int]]):
        for cname, ids in companies.items():
            try:
                actors = self.api.query_actor(TargetsQueryParam(actorId=ids)) if ids else []
                attach_ids = [a.actor_id for a in actors]
                comp = self.companies.get(cname) or CompanyCommander(self.api, self.mapper, cname)
                comp.set_units(attach_ids)
                self.companies[cname] = comp
            except Exception:
                pass

    def compute_center(self) -> Optional[Dict[str, int]]:
        try:
            coords: List[Tuple[int, int]] = []
            for comp in list(self.companies.values()):
                ids = list(getattr(comp, 'unit_ids', []) or [])
                if not ids:
                    continue
                actors = self.api.query_actor(TargetsQueryParam(actorId=ids))
                for a in actors:
                    if getattr(a, 'position', None):
                        coords.append((int(a.position.x), int(a.position.y)))
            if not coords:
                return None
            xs = sorted([x for x, _ in coords])
            ys = sorted([y for _, y in coords])
            mx = xs[len(xs)//2]
            my = ys[len(ys)//2]
            close = [(x, y) for (x, y) in coords if abs(x - mx) + abs(y - my) <= 15]
            if close:
                cx = sum(x for x, _ in close) // len(close)
                cy = sum(y for _, y in close) // len(close)
                return {"x": cx, "y": cy}
            return {"x": mx, "y": my}
        except Exception:
            return None


    def patrol(self):
        cx = (self.bounds[0] + self.bounds[2]) // 2
        cy = (self.bounds[1] + self.bounds[3]) // 2
        for comp in list(self.companies.values()):
            comp.patrol_center((cx, cy))


class ProcessFactory:
    def __init__(self):
        try:
            import importlib
            enhancer_module = importlib.import_module("assistant.tactical_core.enhancer")
            BiodsEnhancer = enhancer_module.BiodsEnhancer
            self.enhancer = BiodsEnhancer(enabled=True)
        except ImportError:
            print("Warning: Failed to import BiodsEnhancer from assistant.tactical_core")
            self.enhancer = None
        self.running = False

    def start(self, api: GameAPIClient, mapper: UnitMapper):
        if self.running or not self.enhancer:
            return
        self.enhancer.start(api)
        self.running = True

    def stop(self):
        if not self.running or not self.enhancer:
            return
        self.enhancer.stop()
        self.running = False


class RLAdaptor:
    def __init__(self):
        self.enabled = False

    def choose_actions(self, observation: Dict[str, Any]) -> List[Tuple[int, int]]:
        return []


class AIHQ:
    def __init__(self, api_client: GameAPIClient, unit_mapper: UnitMapper, command_parser):
        self.api = api_client
        self.mapper = unit_mapper
        self.command_parser = command_parser
        try:
            sec_key = os.environ.get("LLM_SECRETARY_API_KEY") or os.environ.get("ARK_PRE_API_KEY") or os.environ.get("ARK_API_KEY")
            sec_model = os.environ.get("LLM_SECRETARY_MODEL_ID") or "doubao-seed-1-6-251015"
            self.client_secretary = DoubaoClient(api_key=sec_key, model=sec_model)
        except Exception:
            self.client_secretary = None
        try:
            logi_key = os.environ.get("LLM_LOGISTICS_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("ARK_PRE_API_KEY")
            logi_model = os.environ.get("LLM_LOGISTICS_MODEL_ID") or "doubao-seed-1-6-251015"
            self.client_logistics = DoubaoClient(api_key=logi_key, model=logi_model)
        except Exception:
            self.client_logistics = None
        try:
            brig_key = os.environ.get("LLM_BRIGADE_API_KEY") or os.environ.get("ARK_DELEGATE_API_KEY") or os.environ.get("ARK_API_KEY")
            brig_model = os.environ.get("LLM_BRIGADE_MODEL_ID") or os.environ.get("ARK_DELEGATE_MODEL_ID") or "doubao-seed-1-6-flash-250828"
            self.client_brigade = DoubaoClient(api_key=brig_key, model=brig_model)
        except Exception:
            self.client_brigade = None
        try:
            recr_key = os.environ.get("LLM_RECRUIT_API_KEY") or os.environ.get("ARK_INFANTRY_API_KEY") or os.environ.get("ARK_API_KEY")
            recr_model = os.environ.get("LLM_RECRUIT_MODEL_ID") or os.environ.get("ARK_INFANTRY_MODEL_ID") or "doubao-seed-1-6-flash-250828"
            self.client_recruit = DoubaoClient(api_key=recr_key, model=recr_model)
        except Exception:
            self.client_recruit = None
        self.staff = ChiefOfStaff(api_client, unit_mapper)
        self.logistics = LogisticsMinister(api_client, self.client_logistics)
        self.company = CompanyManager()
        self.recruit = RecruitmentMinister(self.client_recruit, self.company)
        try:
            setattr(self.recruit, 'ai_hq_ref', self)
        except Exception:
            pass
        self.process = ProcessFactory()
        self.rl = RLAdaptor()
        self.secretary = Secretary(command_parser, self.client_secretary)
        self.brigades: List[BrigadeCommander] = []
        self.llm_brigade = LLMBrigadeCommander(self.client_brigade)
        self.logistics_runner = LogisticsRunner(self)
        self.logistics_runner.start()
        self.brigade_runner = BrigadeRunner(self)
        self.brigade_runner.start()
        try:
            comp_key = os.environ.get("LLM_COMPANY_API_KEY") or os.environ.get("ARK_INFANTRY_API_KEY") or os.environ.get("ARK_API_KEY")
            comp_model = os.environ.get("LLM_COMPANY_MODEL_ID") or os.environ.get("ARK_INFANTRY_MODEL_ID") or "doubao-seed-1-6-flash-250828"
            client_company = DoubaoClient(api_key=comp_key, model=comp_model)
            self.company_attack_runner = CompanyAttackRunner(self, client=client_company)
        except Exception:
            self.company_attack_runner = CompanyAttackRunner(self)
        self.company_attack_runner.start()
        self.recruitment_runner = RecruitmentRunner(self)
        self.recruitment_runner.start()
        self._init_brigades()
        self._last_ally_base: Optional[Dict[str, int]] = None
        self._last_enemy_base: Optional[Dict[str, int]] = None
        self._auto_logistics_enabled: bool = False
        self._auto_recruit_enabled: bool = False

    def _init_brigades(self):
        try:
            m = {}
            if getattr(self, "_has_started", False):
                m = self.api.map_query() or {}
            w = int(m.get("MapWidth") or m.get("width") or 128)
            h = int(m.get("MapHeight") or m.get("height") or 128)
        except Exception:
            w = 128
            h = 128
        mx = w - 1
        my = h - 1
        xmid = mx // 2
        ymid = my // 2
        zones = [
            (0, 0, xmid, ymid),
            (xmid + 1, 0, mx, ymid),
            (0, ymid + 1, xmid, my),
            (xmid + 1, ymid + 1, mx, my),
        ]
        names = ["第一战区旅长", "第二战区旅长", "第三战区旅长", "第四战区旅长"]
        codes = ["brigade_1", "brigade_2", "brigade_3", "brigade_4"]
        self.brigades = [BrigadeCommander(self.api, self.mapper, names[i], zones[i], codes[i]) for i in range(len(zones))]

    def _update_brigade_zones(self, snap: Dict[str, Any]):
        try:
            m = snap.get("map") or {}
            w = int(m.get("MapWidth") or m.get("width") or 128)
            h = int(m.get("MapHeight") or m.get("height") or 128)
        except Exception:
            w = 128; h = 128
        try:
            cp = getattr(self, 'command_parser', None)
            mc = getattr(cp, 'map_cache', {}) if cp else {}
        except Exception:
            mc = {}
        A = snap.get("ally_base") or (mc.get('last_ally_base') or mc.get('ally_base')) or None
        B = snap.get("enemy_base") or None
        if A:
            self._last_ally_base = {"x": int(A.get("x", 0)), "y": int(A.get("y", 0))}
        if B:
            self._last_enemy_base = {"x": int(B.get("x", 0)), "y": int(B.get("y", 0))}
        ax = int((self._last_ally_base or A or {"x": 0}).get("x", 0))
        ay = int((self._last_ally_base or A or {"y": 0}).get("y", 0))
        if self._last_enemy_base or B:
            bx = int((self._last_enemy_base or B or {"x": w - 1}).get("x", w - 1))
            by = int((self._last_enemy_base or B or {"y": h - 1}).get("y", h - 1))
        else:
            bx = (w - 1) - ax
            by = (h - 1) - ay
        vx = bx - ax
        vy = by - ay
        def closer_to_A(x: int, y: int) -> bool:
            da = abs(x - ax) + abs(y - ay)
            db = abs(x - bx) + abs(y - by)
            return da <= db
        def closer_to_B(x: int, y: int) -> bool:
            da = abs(x - ax) + abs(y - ay)
            db = abs(x - bx) + abs(y - by)
            return db < da
        def left_side(x: int, y: int) -> bool:
            px = x - ax
            py = y - ay
            return (vx * py - vy * px) > 0
        def right_side(x: int, y: int) -> bool:
            px = x - ax
            py = y - ay
            return (vx * py - vy * px) < 0
        for b in self.brigades:
            if getattr(b, 'code', '') == "brigade_1":
                b.set_zone_fn(closer_to_A)
            elif getattr(b, 'code', '') == "brigade_3":
                b.set_zone_fn(closer_to_B)
            elif getattr(b, 'code', '') == "brigade_2":
                b.set_zone_fn(left_side)
            elif getattr(b, 'code', '') == "brigade_4":
                b.set_zone_fn(right_side)

        cx = max(0, min(w - 1, w // 2))
        cy = max(0, min(h - 1, h // 2))
        import math
        dx = cx - ax
        dy = cy - ay
        dist_ac = math.sqrt(float(dx * dx + dy * dy))
        step = (dist_ac / 2.0)
        ux = (dx / dist_ac) if dist_ac > 0 else 1.0
        uy = (dy / dist_ac) if dist_ac > 0 else 0.0
        lx = uy
        ly = -ux
        rx = -uy
        ry = ux
        def _clamp(ix: float, iy: float) -> Dict[str, int]:
            return {"x": max(0, min(w - 1, int(round(ix)))), "y": max(0, min(h - 1, int(round(iy))))}
        c1 = {"x": ax, "y": ay}
        c3 = {"x": cx, "y": cy}
        c2 = _clamp(cx + lx * step, cy + ly * step)
        c4 = _clamp(cx + rx * step, cy + ry * step)
        for b in self.brigades:
            code = getattr(b, 'code', '')
            if code == "brigade_1":
                setattr(b, 'center', c1)
            elif code == "brigade_3":
                setattr(b, 'center', c3)
            elif code == "brigade_2":
                setattr(b, 'center', c2)
            elif code == "brigade_4":
                setattr(b, 'center', c4)

    def _compute_company_centers(self, brigade: 'BrigadeCommander', company_units: Dict[str, List[int]]) -> Dict[str, Dict[str, int]]:
        centers: Dict[str, Dict[str, int]] = {}
        try:
            for cname, ids in company_units.items():
                actors = self.api.query_actor(TargetsQueryParam(actorId=ids)) if ids else []
                coords = [(a.position.x, a.position.y) for a in actors if getattr(a, 'position', None)]
                if not coords:
                    continue
                xs = sorted([x for x, _ in coords])
                ys = sorted([y for _, y in coords])
                mx = xs[len(xs)//2]
                my = ys[len(ys)//2]
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

    def _assign_units(self, allies: List[Dict[str, Any]]):
        brigades_info = []
        for b in self.brigades:
            center = None
            try:
                center = b.compute_center()
            except Exception:
                center = None
            info = {"name": getattr(b, 'name', ''), "code": getattr(b, 'code', ''), "bounds": {"x0": b.bounds[0], "y0": b.bounds[1], "x1": b.bounds[2], "y1": b.bounds[3]}}
            if center:
                info["center"] = center
            brigades_info.append(info)
        snap = self.staff.snapshot()
        self._update_brigade_zones(snap)
        try:
            self.recruitment_runner.set_task({"task": "update_companies", "params": {"reason": "assign_units"}})
        except Exception:
            pass
        for b in self.brigades:
            comps = self.company.get_companies_for_brigade(getattr(b, 'name', ''))
            b.assign_companies(comps)

    def execute_strategic(self, task: StrategicTask) -> Dict[str, Any]:
        snap = self.staff.snapshot()
        self._update_brigade_zones(snap)
        try:
            for b in self.brigades:
                comps = self.company.get_companies_for_brigade(getattr(b, 'name', ''))
                b.assign_companies(comps)
        except Exception:
            pass
        tname = str(getattr(task, 'name', '') or '').strip().lower()
        if tname in {"intercept","engage","engage_enemy","engage_nearby","迎击"}:
            tname = "attack"
        if tname == "attack":
            for b in [x for x in self.brigades if self.company.has_companies(getattr(x, 'name', ''))]:
                try:
                    self.brigade_runner.set_task(getattr(b, 'name', ''), {"mission": "attack", "params": {}, "source": "secretary"})
                except Exception:
                    pass
            return {"success": True, "message": ""}
        if tname == "defend_base":
            base = snap.get("ally_base") or {"x": 0, "y": 0}
            cx = int(base.get("x", 0)); cy = int(base.get("y", 0))
            for b in [x for x in self.brigades if self.company.has_companies(getattr(x, 'name', ''))]:
                try:
                    self.brigade_runner.set_task(getattr(b, 'name', ''), {"mission": "defend_base", "params": {"center": {"x": cx, "y": cy}}, "source": "secretary"})
                except Exception:
                    pass
            return {"success": True, "message": ""}
        if tname == "mine_at_mouse":
            try:
                self.logistics_runner.set_task({"task": "mine_at_mouse", "params": {}})
                if not getattr(self.logistics_runner, '_running', False):
                    self.logistics_runner.start()
                return {"success": True, "message": "后勤：已接收开矿任务并进入循环"}
            except Exception:
                return {"success": False, "message": "开矿任务下达失败"}
        return {"success": False, "message": "未知战略任务"}

    def execute_routes(self, routes: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            print(f"[DEBUG][AIHQ] begin_execute_routes count={len(routes)}")
            print(f"[DEBUG][AIHQ] routes={str(routes)[:200]}{'…' if len(str(routes))>200 else ''}")
        except Exception:
            pass
        snap = self.staff.snapshot()
        try:
            setattr(self, "_last_allies", snap.get("allies", []) or [])
        except Exception:
            pass
        self._update_brigade_zones(snap)
        try:
            for b in self.brigades:
                comps = self.company.get_companies_for_brigade(getattr(b, 'name', ''))
                b.assign_companies(comps)
        except Exception:
            pass
        msgs = []
        ok_any = False
        for r in routes:
            role = str(r.get("role") or "").lower()
            raw_task = str(r.get("task") or "").strip()
            task = raw_task.lower()
            params = r.get("params") or {}
            try:
                print(f"[DEBUG][AIHQ] route role={role} task={task}")
            except Exception:
                pass
            try:
                if role == "brigade":
                    target_brigade = str(params.get("brigade") or "").strip()
                    brigades_iter = [b for b in self.brigades if (not target_brigade or getattr(b, 'name', '') == target_brigade or getattr(b, 'code', '') == target_brigade)]
                    cp = getattr(self, 'command_parser', None)
                    for b in brigades_iter:
                        try:
                            if not self.company.has_companies(getattr(b, 'name', '')):
                                continue
                        except Exception:
                            pass
                        try:
                            print(f"[LLM_JSON][SecretaryTask] {json.dumps({'role': 'brigade', 'target': getattr(b, 'code', getattr(b, 'name', '')), 'text': raw_task, 'params': params}, ensure_ascii=False)}")
                        except Exception:
                            pass
                        try:
                            self.brigade_runner.set_task(getattr(b, 'name', ''), {"mission": raw_task, "mission_raw": raw_task, "params": params, "source": "secretary"})
                        except Exception:
                            pass
                        try:
                            if cp:
                                d = dict(getattr(cp, '_brigade_task_texts', {}) or {})
                                d[getattr(b, 'name', '')] = raw_task
                                setattr(cp, '_brigade_task_texts', d)
                        except Exception:
                            pass
                    msgs.append("旅长：已接收任务")
                    ok_any = True
                elif role == "logistics":
                    try:
                        self.logistics_runner.set_task({"task": raw_task or task, "params": params})
                        try:
                            print(f"[LLM_JSON][SecretaryTask] {json.dumps({'role': 'logistics', 'target': 'logistics', 'text': raw_task or task, 'params': params}, ensure_ascii=False)}")
                            if getattr(self, 'command_parser', None):
                                setattr(self.command_parser, '_logistics_task_text', str(getattr(self.command_parser, '_last_strategic_input', '') or (raw_task or task)))
                        except Exception:
                            pass
                        if not getattr(self.logistics_runner, '_running', False):
                            self.logistics_runner.start()
                        msgs.append("后勤：已接收任务变量并进入循环")
                        ok_any = True
                    except Exception:
                        msgs.append("后勤：任务下达失败")
                elif role == "recruitment":
                    try:
                        self.recruitment_runner.set_task({"task": raw_task or task, "params": params})
                        try:
                            print(f"[LLM_JSON][SecretaryTask] {json.dumps({'role': 'recruitment', 'target': 'recruitment', 'text': raw_task or task, 'params': params}, ensure_ascii=False)}")
                            if getattr(self, 'command_parser', None):
                                setattr(self.command_parser, '_recruitment_task_text', str(getattr(self.command_parser, '_last_strategic_input', '') or (raw_task or task)))
                        except Exception:
                            pass
                        if not getattr(self.recruitment_runner, '_running', False):
                            self.recruitment_runner.start()
                        msgs.append("征兵：已接收任务并进入循环")
                        ok_any = True
                    except Exception:
                        msgs.append("征兵：任务下达失败")
            except Exception:
                msgs.append(f"{role}:{task} 执行失败")
        pass
        return {"success": ok_any, "message": "；".join(msgs) if msgs else "无"}

    def process_input(self, text: str) -> Dict[str, Any]:
        pass
        try:
            setattr(self, "_has_started", True)
        except Exception:
            pass
        try:
            if hasattr(self, 'staff') and self.staff:
                self.staff.mark_started()
        except Exception:
            pass
        preloaded_routes = []
        try:
            preloaded_routes = list(getattr(self.command_parser, "_secretary_routes", []) or [])
        except Exception:
            preloaded_routes = []
        kind = "strategic"
        stask: Optional[StrategicTask] = None
        if preloaded_routes:
            tname = str((preloaded_routes or [{}])[0].get("task") or "")
            stask = StrategicTask(name=tname, params={})
        pass
        pass
        try:
            mapper = getattr(self, 'mapper', None)
            norm = str(text or "")
            if mapper:
                items = sorted(list(mapper.name_to_code.items()), key=lambda kv: len(kv[0]), reverse=True)
                for name, code in items:
                    if name and code and (name in norm):
                        norm = norm.replace(name, code)
            setattr(self.command_parser, "_last_strategic_input", norm)
        except Exception:
            pass
        # 推迟后台循环启动到路由执行之后，确保首轮读取到已设置任务
        routes = []
        try:
            routes = getattr(self.command_parser, "_secretary_routes", []) or []
            if not routes:
                routes = getattr(self, "_last_routes", []) or []
            setattr(self.command_parser, "_secretary_routes", [])
            print(f"[DEBUG][AIHQ] routes_loaded_count={len(routes)}")
        except Exception:
            routes = []
        if routes:
            pass
            result = self.execute_routes(routes)
            # 附加路由摘要，便于UI展示
            try:
                result.setdefault("data", {})
                result["data"]["routes_executed"] = routes
            except Exception:
                pass
            try:
                if not getattr(self.brigade_runner, '_running', False):
                    self.brigade_runner.start()
                if not getattr(self.company_attack_runner, '_running', False):
                    self.company_attack_runner.start()
                if getattr(self, '_auto_logistics_enabled', False) and not getattr(self.logistics_runner, '_running', False):
                    self.logistics_runner.start()
                if getattr(self, '_auto_recruit_enabled', False) and not getattr(self.recruitment_runner, '_running', False):
                    self.recruitment_runner.start()
            except Exception:
                pass
            return result
        if stask and getattr(stask, 'name', None):
            return self.execute_strategic(stask)
        return {"success": False, "message": "秘书未识别战略或当前无可调用旅长"}

    def command_parser_quick(self, text: str) -> Dict[str, Any]:
        try:
            res = self.secretary.command_parser.parse_command_quick(text)
            msg = res.get("result", {}).get("message", "")
            ok = bool(res.get("result", {}).get("success", False))
            return {"success": ok, "message": msg, "data": res.get("result", {}).get("data", {})}
        except Exception:
            return {"success": False, "message": "指令执行失败"}
        try:
            setattr(self.recruit, 'ai_hq_ref', self)
        except Exception:
            pass
