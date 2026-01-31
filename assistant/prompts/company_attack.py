import json

def build_system_prompt(counters_text, zone, center, radius):
    parts = []
    parts.append("你是连长（战斗专家）。根据兵种克制、位置与血量，为每个我方单位分配一个合理的敌方目标。")
    parts.append("克制与优先序：\n" + (counters_text or ""))
    parts.append("作战范围：以目标坐标为圆心、半径为R的区域内所有敌我单位；若无任何敌我单位则不输出。")
    parts.append("输出JSON：[[ally_id,enemy_id],...]；直接输出数组；允许集火。")
    try:
        parts.append("中心：" + json.dumps(center or {}, ensure_ascii=False))
    except Exception:
        parts.append("中心：{}")
    parts.append("半径：" + str(int(radius or 0)))
    try:
        parts.append("敌方：" + json.dumps(zone.get("enemies", []) or [], ensure_ascii=False))
    except Exception:
        parts.append("敌方：[]")
    try:
        parts.append("我方：" + json.dumps(zone.get("allies", []) or [], ensure_ascii=False))
    except Exception:
        parts.append("我方：[]")
    return "\n".join(parts)
