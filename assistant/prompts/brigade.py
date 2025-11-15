import json

def _summarize_zone(zone: dict) -> dict:
    try:
        eb = (zone or {}).get("enemy_base") or {}
        sp = (zone or {}).get("map_points") or {}
        return {"enemy_base": eb, "special_points": sp}
    except Exception:
        return {}

def build_dispatch_prompt(zone, mission, allowed_companies=None):
    parts = []
    parts.append("你是旅长。战区仅供参考，活动范围不受限。你接受秘书的上级任务，并为下属所有可调用连队分配明确的前往坐标。")
    parts.append("上级任务：" + str(mission or ""))
    parts.append("连队名称采用标准化命名 ‘brigade_#_companyN’，仅使用该名称进行引用。")
    parts.append("连队特征与部署建议：\n- company1（主力装甲）：以 3tnk/4tnk 为主，建议部署于正面主战场坐标；\n- company2（远程火炮）：以 v2rl 为主，较为脆弱，建议部署在一连后方的适度距离；\n- company3（包抄奇袭/预备队）：以 3tnk/ftrk 为主，若可用则编入 yak/mig，建议用于敌后或侧翼包抄位置。")
    parts.append("优先级规则：\n1) 任何非空的上级任务文本均视为明确任务，必须严格执行并保持；\n2) 若任务包含‘待命/驻守/守卫/集结/到达后待命’等持续性语义，视为持续任务：到达指定位置后必须持续原地待命，直到收到秘书的新任务；\n3) 禁止在持续任务期间将任务标记为完成或清除（禁止输出 meta.task_complete=true 或 tools.complete_task）；\n4) 无上级任务时，如能在连队附近观测到敌情（根据 company_centers 与 zone.enemies 距离），择近选择合理作战坐标；\n5) 若附近无敌情且无上级任务，仅将本旅‘防区中心点’作为临时集结参考并‘待命’，此情形不视为任务完成。每个可调用连队必须输出一个 dispatch，其 location 应靠近 zone.brigade_center（曼哈顿距离≤10），位置并非固定一点，可根据地形与兵力在中心点附近择优。")
    parts.append("派遣覆盖范围：本次输出必须为所有可调用连队（allowed_companies）各分配一个且仅一个 dispatch 项，确保覆盖完整与不重复。")
    parts.append("任务完成约束：仅当秘书明确下令‘取消/结束/撤销’该任务或一次性目标已达成且不属于‘待命/驻守/守卫/巡逻/集结待命’时，方可在 meta 中标记 task_complete=true。持续任务期间不得标记完成。")
    parts.append("文本坐标词映射：当上级任务出现方位词时，结合 zone.map_points：‘上中’=top_center，‘下中’=bottom_center，‘左中’=left_center，‘右中’=right_center，‘中间/中心’=center/middle。无明确坐标时，优先使用上述点位；存在明确坐标则以明确坐标为准。")
    parts.append("数据目录：\n- zone.enemies: 敌方全体单位与建筑 [{id,type,x,y}]\n- zone.company_units: {连队名:[unit_ids]}\n- zone.company_centers: {连队名:{x,y}}\n- zone.brigade_center: 本旅防区中心点坐标 {x,y}\n- zone.companies: 可调度连队名集合（名称）。")
    try:
        parts.append("辖区数据：" + json.dumps(zone or {}, ensure_ascii=False))
    except Exception:
        parts.append("辖区数据：{}")
    try:
        parts.append("连队中心点(JSON)：" + json.dumps(((zone or {}).get("company_centers") or {}), ensure_ascii=False))
    except Exception:
        parts.append("连队中心点(JSON)：{}")
    try:
        parts.append("可调动连队：" + json.dumps(allowed_companies or [], ensure_ascii=False))
    except Exception:
        parts.append("可调动连队：[]")
    try:
        bc = (zone or {}).get("brigade_center") or {}
        cx = str(bc.get("x") if isinstance(bc, dict) else "")
        cy = str(bc.get("y") if isinstance(bc, dict) else "")
        parts.append("再次强调：本旅‘防区中心点’坐标为 (" + cx + "," + cy + ")。仅在‘无上级任务且附近无敌情’时，才在该中心点附近择优位置‘集结待命’；此为临时待命，不得视为任务完成。")
        parts.append("旅长辖区中心点坐标：(" + cx + "," + cy + ")")
    except Exception:
        parts.append("再次强调：本旅‘防区中心点’坐标为 zone.brigade_center。在无上级任务且附近无敌情时，所有可调用连队需在该中心点附近择优位置集结待命。")
    summary = _summarize_zone(zone or {})
    try:
        eb = summary.get("enemy_base") or {}
        ex = int(eb.get("x")) if isinstance(eb, dict) and eb.get("x") is not None else None
        ey = int(eb.get("y")) if isinstance(eb, dict) and eb.get("y") is not None else None
        observed = bool((zone or {}).get("enemy_base_observed"))
        if ex is not None and ey is not None:
            label = f"敌方基地坐标：({ex},{ey})" + ("" if observed else "(缓存)")
            parts.append(label)
    except Exception:
        pass
    try:
        sps = summary.get("special_points") or {}
        parts.append("地图特殊点位(JSON)：" + json.dumps(sps, ensure_ascii=False))
    except Exception:
        parts.append("地图特殊点位(JSON)：{}")
    parts.append("输出JSON：{\"dispatch\":[{\"company\":\"brigade_#_companyN\",\"location\":{\"x\":int,\"y\":int}},...],\"tools\":[{\"op\":\"relocate\",\"company\":\"brigade_#_companyN\",\"location\":{\"x\":int,\"y\":int},\"mode\":\"assault|attack|normal\"}],\"meta\":{\"task_complete\":false}}。\n派遣用于触发连长的局部作战分配；当上级任务包含明确的到达/集结语义或需要强制位移时，必须在 tools 中为对应连队加入一条 relocate 项以确保单位前往指定坐标。持续任务（待命/驻守/守卫/巡逻/集结待命）期间必须保持 task_complete=false。")
    return "\n".join(parts)
