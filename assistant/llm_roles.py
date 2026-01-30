import json
from typing import Dict, Any, List, Optional, Tuple

from .doubao_client import DoubaoClient
from .api_client import GameAPIClient, TargetsQueryParam, Location
from .prompts.secretary import build_system_prompt as build_secretary_system_prompt
from .prompts.logistics import build_system_prompt as build_logistics_system_prompt
from .prompts.brigade import build_dispatch_prompt as build_brigade_dispatch_prompt
from .prompts.company_attack import build_system_prompt as build_company_attack_prompt
from .prompts.recruitment import build_system_prompt as build_recruitment_system_prompt


class LLMRole:
    def __init__(self, client: DoubaoClient):
        self.client = client

    def call_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> Dict[str, Any]:
        if self.client is None:
            return {}
        try:
            out = self.client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=max_tokens)
            try:
                return json.loads(out)
            except Exception:
                return {}
        except Exception as e:
            return {}


class LLMSecretary(LLMRole):
    def classify(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        brigades_info = (context or {}).get("brigades_info") if isinstance(context, dict) else None
        battlefield = (context or {}).get("battlefield") if isinstance(context, dict) else None
        companies = (context or {}).get("companies") if isinstance(context, dict) else None
        from .prompts.secretary import build_system_prompt as build_secretary_system_prompt
        system_prompt = build_secretary_system_prompt(text, brigades_info, battlefield, companies)
        try:
            lines = str(system_prompt).splitlines()
            for ln in lines:
                if ("敌方基地坐标：" in ln) or ("地图特殊点位(JSON)：" in ln):
                    print(f"[LLM_PROMPT_LINE][Secretary] {ln}")
        except Exception:
            pass
        user_prompt = str(text or "开始")
        res = self.call_json(system_prompt, user_prompt, max_tokens=2048) or {}
        try:
            print(f"[LLM_JSON][Secretary] {json.dumps(res, ensure_ascii=False)}")
        except Exception:
            pass
        try:
            from .command_parser import CommandParser  # type: ignore
            cp = getattr(self, 'command_parser', None)
            if cp:
                setattr(cp, '_secretary_report', res.get('report'))
        except Exception:
            pass
        return res


class LLMLogistics(LLMRole):
    def plan(self, battlefield: Dict[str, Any], task_directive: Optional[Dict[str, Any]] = None, recruitment_advisory: Optional[Dict[str, Any]] = None, recent_decisions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        system_prompt = build_logistics_system_prompt(battlefield, task_directive, recruitment_advisory, recent_decisions)
        user_prompt = "开始"
        return self.call_json(system_prompt, user_prompt, max_tokens=4096)

    def execute(self, api: GameAPIClient, plan: Dict[str, Any]) -> str:
        tools = plan.get("tools") or []
        results: List[str] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            ttype = str(t.get("type") or "").lower()
            unit = t.get("unit")
            qty = int(t.get("quantity") or 1)
            queue = t.get("queue") or "Building"
            try:
                if ttype in {"produce", "build"}:
                    ql = str(queue).strip()
                    ul = str(unit or "").strip().lower()
                    if ql == "Defense" or ul in {"ftur","tsla","sam","harv"}:
                        results.append("skip defense")
                        continue
                    if ql == "Vehicle":
                        qty = max(2, min(qty, 5))
                    elif ql == "Infantry":
                        qty = max(5, qty)
                    ok, _ = api.produce_unit(unit, qty, queue)
                    if ok:
                        results.append(f"{ttype} {qty} {unit}")
                    else:
                        results.append(f"fail {unit}")
                else:
                    results.append(f"skip {ttype}")
            except Exception:
                results.append(f"error {unit}")
        return ", ".join(results) if results else "no tools"


class LLMBrigadeCommander(LLMRole):
    def plan_dispatch(self, zone: Dict[str, Any], mission: str, allowed_companies: List[str]) -> Dict[str, Any]:
        system_prompt = build_brigade_dispatch_prompt(zone, mission, allowed_companies)
        try:
            lines = str(system_prompt).splitlines()
            for ln in lines:
                if ("地图特殊点位(JSON)：" in ln) or ("敌方基地坐标" in ln) or ("连队中心点(JSON)：" in ln) or ("旅长辖区中心点坐标：" in ln):
                    print(f"[LLM_PROMPT_LINE][Brigade] {ln}")
        except Exception:
            pass
        user_prompt = "开始"
        res = self.call_json(system_prompt, user_prompt, max_tokens=4096) or {}
        try:
            print(f"[LLM_JSON][Brigade] {json.dumps(res, ensure_ascii=False)}")
        except Exception:
            pass
        return res

    def execute_dispatch(self, api: GameAPIClient, company_units: Dict[str, List[int]], dispatch: List[Dict[str, Any]]) -> Tuple[bool, str]:
        if not dispatch:
            return False, "empty"
        ok_any = False
        for d in dispatch:
            try:
                cname = str(d.get("company") or "")
                loc = d.get("location") or {}
                ids = company_units.get(cname) or []
                if not ids:
                    continue
                actors = api.query_actor(TargetsQueryParam(actorId=ids))
                api.move_units_by_location(actors, Location(int(loc.get("x", 0)), int(loc.get("y", 0))), attack_move=False, assault_move=False)
                ok_any = True
            except Exception:
                pass
        return ok_any, "dispatch"


class LLMCompanyAttack(LLMRole):
    def get_counters_text(self) -> str:
        return "\n".join([
            "单位分类 (Category) 与代码 (Code) 对照表（所有阵营通用）：",
            "- 重要目标: mcv (基地车)",
            "- 步兵 (INF):",
            "  * 炮灰 (INF_MEAT): e1",
            "  * 反甲/防空 (INF_AT): e3",
            "- 车辆 (VEHICLE):",
            "  * 主战 (MBT): 2tnk, 3tnk, 4tnk, ctnk",
            "  * 远程 (ARTY): v2rl, arty",
            "  * 轻型/防空 (AFV): ftrk, jeep, 1tnk, apc",
            "  * 后勤: harv (矿车)",
            "- 防御 (DEFENSE):",
            "  * 对空: sam, agun",
            "  * 反步兵: ftur, pbox",
            "  * 反坦克: tsla, gun",
            "- 飞机 (AIRCRAFT): yak, mig, heli, mh60",
            "- 建筑 (BUILDING): fact (建造厂), 其他 (weap, barr, pwr, dome, fix, proc...)",
            "",
            "全局核心规则：",
            "1. **对空限制**：仅 e3, 4tnk, ftrk, heli, sam, agun 具有对空能力。严禁分配其他单位攻击飞机。",
            "2. **斩首行动**：如果 mcv (基地车) 可见且在射程内，所有单位最高优先级攻击 mcv。",
            "3. **威胁优先**：战斗单位/防御 > 建筑。拆建筑仅在无威胁时进行。",
            "4. **建筑拆除**：优先拆除 fact (建造厂)，其他建筑归为最低优先级，不区分顺序。",
            "",
            "基于 UnitCategory 的兵种克制与优先攻击链：",
            "- **INF_AT (e3)**: 优先攻击 -> MBT (主战坦克)。",
            "- **INF_MEAT (e1)**: 优先攻击 -> INF_AT (e3)。(利用数量优势消耗高价值步兵)",
            "- **MBT (2tnk/3tnk/ctnk)**: 优先攻击 -> ARTY (切后排) > MBT (对决) > AFV。",
            "  * 战术建议：可分出少量 MBT 突袭敌方后排 ARTY，扰乱敌方阵型。",
            "- **AFV (jeep/1tnk/apc)**: 优先攻击 -> ARTY (利用高机动偷袭) > INF/AFV。",
            "- **AFV (ftrk)**: 优先攻击 -> AIRCRAFT (防空第一) > ARTY > INF/AFV。",
            "- **ARTY (v2rl/arty)**: 优先攻击 -> 密集的 INF (AOE杀伤最大化) > ARTY (反炮兵) > DEFENSE (射程外拆塔)。",
            "",
            "通用决策建议（自主权）：",
            "1. **综合决策**：请综合考虑兵种克制、敌方血量、距离、敌方密度和我方位置。",
            "2. **多点开花**：避免将所有火力集中于一点，建议形成多个局部火力优势点。",
            "3. **动态平衡**：在“优先击杀最近威胁”与“突袭高价值后排（如 ARTY/MCV）”之间寻找平衡。例如，用主力抗线的同时，分兵骚扰敌方后排。",
        ])
    def plan_stream(self, counters_text: str, zone: Dict[str, Any], center: Dict[str, int], radius: int) -> Dict[str, Any]:
        system_prompt = build_company_attack_prompt(counters_text, zone, center, radius)
        user_prompt = "开始"
        if not self.client:
            return {}
        out_pairs: List[List[int]] = []
        try:
            if hasattr(self.client, 'chat_json_stream'):
                buffer = ""
                for delta in self.client.chat_json_stream(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=16384):
                    if not delta:
                        continue
                    buffer += delta
                    try:
                        data = json.loads(buffer)
                        arr = data.get("pairs") if isinstance(data, dict) else None
                        if isinstance(arr, list):
                            out_pairs = [p for p in arr if isinstance(p, list) and len(p) == 2 and all(isinstance(x, int) for x in p)]
                    except Exception:
                        pass
                return {"pairs": out_pairs}
        except Exception:
            pass
        try:
            raw = self.client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=4096)
            data = json.loads(raw)
            arr = data.get("pairs") if isinstance(data, dict) else None
            if isinstance(arr, list):
                out_pairs = [p for p in arr if isinstance(p, list) and len(p) == 2 and all(isinstance(x, int) for x in p)]
        except Exception:
            pass
        return {"pairs": out_pairs}

    def plan_stream_execute(self, api: GameAPIClient, counters_text: str, zone: Dict[str, Any], center: Dict[str, int], radius: int) -> Dict[str, Any]:
        system_prompt = build_company_attack_prompt(counters_text, zone, center, radius)
        user_prompt = "开始"
        out_pairs: List[List[int]] = []
        if not self.client:
            return {"pairs": out_pairs}
        try:
            if hasattr(self.client, 'chat_json_stream'):
                buffer = ""
                for delta in self.client.chat_json_stream(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=16384):
                    if not delta:
                        continue
                    buffer += delta
                    try:
                        data = json.loads(buffer)
                        arr = data.get("pairs") if isinstance(data, dict) else None
                        if isinstance(arr, list):
                            pairs = [p for p in arr if isinstance(p, list) and len(p) == 2 and all(isinstance(x, int) for x in p)]
                            if pairs:
                                out_pairs = pairs
                                self.execute_pairs(api, pairs)
                    except Exception:
                        pass
                return {"pairs": out_pairs}
        except Exception:
            pass
        return self.plan_stream(counters_text, zone, center, radius)

    def execute_pairs(self, api: GameAPIClient, pairs: List[List[int]]) -> bool:
        if not pairs:
            return False
        try:
            attackers = [p[0] for p in pairs]
            targets = [p[1] for p in pairs]
            a_actors = api.query_actor(TargetsQueryParam(actorId=attackers)) if attackers else []
            t_actors = api.query_actor(TargetsQueryParam(actorId=targets)) if targets else []
            return bool(api.attack_targets(a_actors, t_actors))
        except Exception:
            return False


class LLMRecruitment(LLMRole):
    def plan(self, allies: List[Dict[str, Any]], brigades_info: List[Dict[str, Any]], battlefield: Dict[str, Any], companies_snapshot: Dict[str, Any], unassigned_units: List[Dict[str, Any]], task: Optional[str] = None) -> Dict[str, Any]:
        system_prompt = build_recruitment_system_prompt(allies, brigades_info, battlefield, companies_snapshot, unassigned_units, task=task)
        user_prompt = "开始"
        return self.call_json(system_prompt, user_prompt, max_tokens=2048)
