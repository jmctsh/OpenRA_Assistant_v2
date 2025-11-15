import json

def _summarize(bf: dict) -> dict:
    try:
        base = bf.get("base", {}) or {}
        queues = bf.get("queues", {}) or {}
        q_summary = {k: len((queues.get(k, {}) or {}).get("queue_items", []) or []) for k in ("Building","Defense","Infantry","Vehicle","Aircraft")}
        return {
            "funds": (base.get("Cash", 0) or 0) + (base.get("Resources", 0) or 0),
            "power_available": base.get("Power", 0),
            "queues": q_summary
        }
    except Exception:
        return {}

def _compact(bf: dict) -> dict:
    try:
        base = bf.get("base", {}) or {}
        ally_base = bf.get("ally_base") or {}
        queues = bf.get("queues", {}) or {}
        ally_building_counts = bf.get("ally_building_counts") or {}
        qp = {}
        for k in ("Building","Defense","Infantry","Vehicle","Aircraft"):
            q = (queues.get(k, {}) or {})
            qp[k] = {
                "busy": bool(q.get("busy")),
                "has_ready_item": bool(q.get("has_ready_item")),
                "count": len((q.get("queue_items", []) or []))
            }
        ally_counts = {}
        try:
            for u in (bf.get("allies") or []):
                t = str(u.get("type") or "").lower()
                if not t:
                    continue
                ally_counts[t] = ally_counts.get(t, 0) + 1
        except Exception:
            ally_counts = {}
        return {
            "funds": (base.get("Cash", 0) or 0) + (base.get("Resources", 0) or 0),
            "power_available": base.get("Power", 0),
            "ally_base": ally_base,
            "queues": qp,
            "ally_unit_counts": ally_counts,
            "ally_building_counts": ally_building_counts
        }
    except Exception:
        return {}

def build_system_prompt(battlefield, task_directive=None, recruitment_advisory=None, recent_decisions=None):
    parts = []
    parts.append("你是后勤部长。你的职责是：‘建筑建造’与‘兵力补充’，不进行防御构筑与开矿相关操作。请基于队列与资源约束输出工具列表。")
    parts.append("全局规则：\n- 不同生产队列彼此独立，可并行：可同时向不同队列（Building/Infantry/Vehicle/Aircraft）下达建造/生产任务；每个队列仅在 busy=false 时提交；Building 队列一次只建1个；\n- 单位提交到正确队列（见 UnitQueueMap）；\n- 电力不足阈值：power_available<150 时，立刻建造 apwr。\n- power/proc/barr/weap/dome 至少1；\n- proc 至少1、最多5；weap 至少1、最多2（仅在经济良好时考虑第2个 ）；\n- 若无法建造（常见因前置不足），须先补齐前置再尝试；\n- fact 门禁：地图上无 fact 时，禁止 Building 的建造。")
    parts.append("运营节奏（资金/趋势驱动）：\n- 资金过少或趋势显著下降（funds<2000 或 delta<-1000）：维持必要军备与补员；\n- 资金充裕且趋势 up（funds>2000 且 trend=up）：可补齐缺失功能性建筑并适度扩大军备；\n- 始终遵守 busy=false 与‘最多1个’规则。")
    parts.append("编制建议与维持（参考）：\n- Vehicle（无stek）：以 3tnk 与 v2rl 为主（约各50%）；有stek：3tnk≈45%、v2rl≈35%、4tnk≈25%；按 ally_unit_counts 动态调整；\n- 主战单位连续生产：仅在 Vehicle 队列 busy=false 时补充 3tnk/v2rl/4tnk，避免队列堆积；\n- 步兵维持：维持 e1=20、e3=10，不足则补足（一次 quantity≤5）；\n- 专项单位：yak 维持=1、ftrk 维持=5；mig 不主动建造；harv 不建造；\n- 本条为目标参考，需结合资金、电力与队列状态自主权衡，严禁超额与越队列。")
    parts.append("单位建造前置（PrerequisitesMap）：\n{\"power\":[],\"proc\":[\"power\"],\"barr\":[\"power\"],\"weap\":[\"proc\"],\"dome\":[\"proc\"],\"apwr\":[\"dome\"],\"fix\":[\"weap\"],\"afld\":[\"dome\"],\"stek\":[\"dome\"],\"e1\":[\"barr\"],\"e3\":[\"barr\"],\"ftrk\":[\"weap\"],\"3tnk\":[\"weap\",\"fix\"],\"v2rl\":[\"weap\",\"dome\"],\"4tnk\":[\"weap\",\"stek\",\"fix\"],\"yak\":[\"afld\"],\"mig\":[\"afld\",\"stek\"]}")
    parts.append("队列映射（UnitQueueMap）：\n{\"Building\":[\"power\",\"proc\",\"barr\",\"weap\",\"dome\",\"apwr\",\"fix\",\"afld\",\"stek\"],\"Infantry\":[\"e1\",\"e3\"],\"Vehicle\":[\"ftrk\",\"3tnk\",\"v2rl\",\"4tnk\"],\"Aircraft\":[\"yak\",\"mig\"]}")
    parts.append("建造/生产输出格式（严格）：\n{\"tools\":[{\"type\":\"produce\",\"unit\":\"<code>\",\"quantity\":<int>,\"queue\":\"Building|Infantry|Vehicle|Aircraft\",\"reason\":\"<简短原因>\"},...],\"meta\":{}}；无动作输出 {\"tools\":[]}。")
    parts.append("生产数量建议：Vehicle 队列每次每个单位 2-5 个；Infantry 队列每次≥5；允许一次输出多条组合生产工具项；前者优先进入队列。")
    parts.append("优先级：task_directive 为参考项而非强制；不得因其而打断或覆盖正常生产节奏与安全原则。始终以‘队列空闲/前置充足/电力充足/资金与趋势’为首要依据。与提示词中的原则同等级；当冲突或不适配时（队列忙/电力不足/资金不足/前置缺失），忽略或延后该参考项。recruitment_advisory 同样为引导，非强制。")
    parts.append("task_directive 变量：当上级提供运营任务时，仅在不冲突的条件下采用（队列空闲且不违反上限与前置），否则择优执行正常生产；若判断该参考项已完成，请在输出 JSON 中加入 meta:{\"task_complete\":true}。")
    parts.append("数据目录：battlefield.base/queues/ally_base；ally_unit_counts=我方作战单位的类型数量统计；ally_building_counts=我方建筑的类型数量统计；recent_decisions=近5次已提交的建造决策（含status=ok/fail/skip/error）；task_directive=来自秘书的运营任务变量(JSON)；recruitment_advisory=来自征兵部长的留言(JSON)。")
    try:
        if task_directive:
            parts.append("task_directive(JSON)：" + json.dumps(task_directive, ensure_ascii=False))
        else:
            parts.append("task_directive(JSON)：null")
    except Exception:
        parts.append("task_directive(JSON)：null")
    try:
        if recruitment_advisory:
            parts.append("recruitment_advisory(JSON)：" + json.dumps(recruitment_advisory, ensure_ascii=False))
        else:
            parts.append("recruitment_advisory(JSON)：null")
    except Exception:
        parts.append("recruitment_advisory(JSON)：null")
    try:
        if recent_decisions:
            parts.append("recent_decisions(JSON)：" + json.dumps(recent_decisions or [], ensure_ascii=False))
        else:
            parts.append("recent_decisions(JSON)：[]")
    except Exception:
        parts.append("recent_decisions(JSON)：[]")
    try:
        parts.append("战场摘要：" + json.dumps(_summarize(battlefield or {}), ensure_ascii=False))
    except Exception:
        parts.append("战场摘要：{}")
    try:
        parts.append("战场精简(JSON)：" + json.dumps(_compact(battlefield or {}), ensure_ascii=False))
    except Exception:
        parts.append("战场精简(JSON)：{}")
    # 提示‘历史+当前’整合与失败反思
    try:
        # 历史提交计数（Building 类别，视为已建造+1）
        hist_counts = {}
        for it in (recent_decisions or []) or []:
            if str(it.get("queue") or "").lower() == "building":
                u = str(it.get("unit") or "").lower()
                if u:
                    hist_counts[u] = hist_counts.get(u, 0) + 1
        parts.append("历史提交计数(JSON)：" + json.dumps(hist_counts, ensure_ascii=False))
    except Exception:
        hist_counts = {}
        parts.append("历史提交计数(JSON)：{}")
    try:
        # 有效建筑计数（effective_counts）= 当前 ally_building_counts + 历史提交计数 hist_counts
        curr = (_compact(battlefield or {}).get("ally_building_counts") or {}) if battlefield else {}
        eff = {}
        for k in set(list(curr.keys()) + list(hist_counts.keys())):
            eff[k] = int(curr.get(k, 0)) + int(hist_counts.get(k, 0))
        parts.append("effective_counts(JSON)：" + json.dumps(eff, ensure_ascii=False))
    except Exception:
        parts.append("effective_counts(JSON)：{}")
    parts.append("注意：严禁输出除上述 JSON 外的任何文本；不得使用未知代码；遵守 busy=false、前置条件与‘严格上限’（以 effective_counts 为准）与‘最多1个’规则；若历史中存在失败，请反思并给出纠正方案（如先补前置/先补电力/等待队列空闲）。")
    s = "\n".join(parts)
    try:
        s = s if len(s) <= 6000 else s[:6000]
    except Exception:
        pass
    return s
