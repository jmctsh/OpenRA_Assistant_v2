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
            "单位分类与英文代码：",
            "- 建筑: fact, power, apwr, barr, proc, weap, dome, fix, afld, stek",
            "- 防御: ftur, tsla, sam",
            "- 步兵: e1, e3",
            "- 车辆: harv, mcv, 3tnk, 4tnk, v2rl, ftrk",
            "- 飞机: mig, yak",
            "",
            "全局核心规则：",
            "1) 最高优先级：mcv（敌方基地车）。如果可见且可达，所有类型优先攻击 mcv。",
            "2) 战斗单位与防御优先于建筑。建筑内部：fact（建造厂）≥ stek（科技中心）>> weap > dome/afld > power/apwr > fix > proc。",
            "3) sam 只对空，若我方没有飞机（yak/mig）参与，则降低 sam 优先度到最低。",
            "4) harv（矿车）仅在其附近没有敌方战斗单位/防御时才可作为优先目标；若附近有防御或战斗单位，应先清理这些威胁。",
            "5) 距离规则：在同一优先级层内，优先攻击几何距离最近的目标，避免跨图追击。",
            "6) 适配性：不要给无法有效攻击的单位分配错误目标（例如：没有空对空能力的单位不要分配去打飞机）。",
            "7) 肉盾与输出：e1/3tnk/4tnk 属于肉盾，优先承受火力但仍应攻击最近的高威胁目标；e3/v2rl/ftrk/mig/yak 属于输出/脆皮，避免深追，优先就近击杀高价值目标。",
            "8) 防御威胁由我方编制决定：若我方有坦克（3tnk/4tnk），提升 tsla 的优先级；若我方多步兵（e1/e3），提升 ftur 的优先级；若我方有飞机（yak/mig），提升 sam 的优先级。",
            "9) 集火规则：在兵种克制的前提下，多个我方单位应优先集火攻击同一敌方单位，避免火力分散。优先依据 hp/maxHp 比例（越低越优先）击杀高价值目标。",
            "",
            "单位价值分层：",
            "- 高价值：mcv、e3、v2rl、ftrk、3tnk/4tnk、yak/mig、tsla/ftur",
            "- 中价值：其他车辆、sam",
            "- 低价值：e1、建筑",
            "",
            "执行建议（关于 e1 处理）：当存在更高价值目标时，避免让重火力（3tnk/4tnk/v2rl/mig）追打 e1；清理 e1 更适合由 yak/ftrk 或就近顺手处理；集火优先于高价值或残血目标。",
            "",
            "全局基础优先序（从高到低，供同类项比较时参考）：",
            "mcv > e3 > v2rl > (tsla/ftur/sam 视我方编制决定其在此层或下一层) > ftrk > 3tnk > 4tnk > fact/stek > weap > dome/afld > power/apwr > fix > proc > harv(在无护卫时上移至 weap 之前)",
            "",
            "按我方单位类型的目标选择优先序（从高到低；同层按最近距离）：",
            "- 我方 e1：mcv > e3 > e1 > ftur > harv(无护卫) > barr > fact > stek > weap > power/apwr > dome/afld > proc",
            "  说明：e1 伤害低，更多承担吸引火力；尽量就近点杀 e3/ftur，建筑普遍靠后。fact 与 stek 同层，优先就近。",
            "- 我方 e3：mcv > (yak/mig) > 3tnk > 4tnk > ftrk > v2rl > tsla > e3 > ftur > fact > stek > weap > dome/afld > power/apwr > proc > harv(无护卫)",
            "  说明：e3 擅长对空与反装甲，优先打飞机与坦克与关键车辆；避免冲锋。fact 略高于 stek。",
            "- 我方 3tnk：mcv > e3 > v2rl > ftur > tsla > ftrk > 3tnk > 4tnk > fact > stek > weap > dome/afld > power/apwr > proc > harv(无护卫)",
            "  说明：先清高威胁（e3/v2rl），对防御优先清 ftur（克步兵），使步兵更安全推进；自身为肉盾，靠前抗伤但仍选近目标。",
            "- 我方 4tnk：mcv > e3 > v2rl > ftur > tsla > 4tnk > 3tnk > ftrk > fact > stek > weap > dome/afld > power/apwr > proc > harv(无护卫)",
            "  说明：综合能力强并具对空，防御目标按 ftur > tsla 处理。",
            "- 我方 v2rl：mcv > e3(群体优先) > ftrk > v2rl > tsla > 3tnk > 4tnk > ftur > fact > stek > weap > dome/afld > power/apwr > proc",
            "  说明：长射程AOE，优先清步兵特别是 e3；其次清对自身威胁或高价值车辆/防御；尽量保持后排，不要追击。",
            "- 我方 ftrk：mcv > (yak/mig) > e3 > e1 > v2rl > ftrk > 3tnk > 4tnk > fact > stek > weap > dome/afld > power/apwr > proc > harv(无护卫)",
            "  说明：擅长对空与对步兵；对坦克效果差，不要冲锋，优先清空 e3。",
            "- 我方 mig：mcv > v2rl > ftrk > tsla > e3 > ftur > 3tnk > 4tnk > e1 > fact > stek > weap > dome/afld > power/apwr > proc",
            "  说明：显著克制车辆和防御；对密集步兵（尤其 e3）也有效。敌方步兵密集时，可将 e3 提升至 ftur 之前；建筑靠后。",
            "- 我方 yak：mcv > e3 > e1 > v2rl > ftrk > 3tnk > 4tnk > tsla > ftur > fact > stek > weap > dome/afld > power/apwr > proc",
            "  说明：显著克制步兵，优先步兵；次选轻甲/防空车辆；再选防御；重甲之后，建筑最后。",
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
