import json

def _summarize_battlefield(bf: dict) -> dict:
    try:
        base = bf.get("base", {}) or {}
        allies = bf.get("allies", []) or []
        enemies = bf.get("enemies", []) or []
        ally_buildings = bf.get("ally_buildings", []) or []
        enemy_buildings = bf.get("enemy_buildings", []) or []
        companies_overview = bf.get("companies_overview", []) or []
        ally_base = bf.get("ally_base") or {}
        enemy_base = bf.get("enemy_base") or {}
        def _slim(lst):
            try:
                out = []
                for it in (lst or []):
                    t = it.get("type")
                    x = it.get("x")
                    y = it.get("y")
                    if t is None or x is None or y is None:
                        continue
                    out.append({"type": str(t), "x": int(x), "y": int(y)})
                return out
            except Exception:
                return []
        return {
            "funds": (base.get("Cash", 0) or 0) + (base.get("Resources", 0) or 0),
            "power_available": base.get("Power", 0),
            "ally_base": ally_base,
            "enemy_base": enemy_base,
            "special_points": bf.get("special_points", {}) or {},
            "ally_buildings": _slim(ally_buildings),
            "enemy_buildings": _slim(enemy_buildings),
            "enemy_units": _slim(enemies),
            "companies_overview": companies_overview
        }
    except Exception:
        return {}

def _compact_companies(snap: dict) -> dict:
    try:
        companies = (snap.get("companies") or {})
        brig = (snap.get("brigades") or {})
        return {
            "company_count": len(companies or {}),
            "brigades": {k: list(v or []) for k, v in brig.items()}
        }
    except Exception:
        return {}

def build_system_prompt(input_text, brigades_info, battlefield, companies_snapshot=None):
    parts = []
    parts.append("你是OpenRA的秘书。你的职责：理解司令战略意图，将任务拆分并下发到最相关、可用的下级角色，必要时同时下发给多个角色。")
    parts.append("工作目标：必须同时完成两个任务：1) 生成下发到下级的 routes；2) 生成面向司令的简短执行情况报告 report。")
    parts.append("下级角色目录：\n- logistics：后勤部长（生产/建造），\n- brigade：旅长（辖区战术分配：进攻/防守/骚扰/巡逻/侦察），\n- recruitment：征兵部长（编制划分/增援分配/合并残部/撤销无战斗力编制）。")
    parts.append("旅长说明：旅长集合为动态且仅显示‘可调用’旅长，来自 brigades_info。")
    parts.append("可调用旅长定义：旅长代码存在于 brigades_info，且在连队综述 companies_overview 中该旅长名下至少有一个连队，并且该连队单位数量>0；否则视为‘不可调用’。")
    parts.append("旅长路由限制：仅为‘可调用’旅长生成 route；禁止为‘不可调用’旅长或不在 brigades_info 中的旅长代码生成任何 route；当需指派给特定旅长，必须在 route.params 中加入 {\"brigade\":\"brigade_#\"} 并且该代码必须出现在 brigades_info。")
    parts.append("工作流程：\n1) 意图分析与任务分解：识别并拆分为[进攻、防御、调遣集结、巡逻、侦察、建造]，允许同时存在多个任务。\n2) 路由分配：按任务类别选择下级并生成 routes。\n   - 建造类：仅路由给后勤部长（logistics），不路由旅长。\n   - 进攻/防御/调遣集结/巡逻/侦察：仅为‘可调用旅长’路由（brigade），每个‘可调用旅长’必须分别生成一条独立 route，且 route.params 必须包含 {brigade:\"brigade_#\"}；坐标结合本旅‘中心(JSON)’与地图特殊点位或敌我基地坐标，分别选择最合理位置；任务允许因战区不同而不同（如靠近敌基者attack，其他旅长rally/harass/patrol）。\n   - 大规模进攻或大规模防御：除旅长任务外，必须联动征兵部长（recruitment.assign），并在 params.reinforcements 中倾斜主攻/主防旅长（进攻倾斜 brigade_3，防御倾斜 brigade_1）。\n3) 战场审读与边界：结合敌我单位（英文代码+坐标）、基地坐标与特殊点位，决定是否多旅长并发。\n4) 不可调用兜底：若不存在任何‘可调用旅长’，则 routes 中不包含任何 brigade 项，并在 report 说明‘当前无可调用旅长’。")
    parts.append("调度约定：当司令说‘进攻/攻击/防御’某处且未明确‘所有人’，默认根据战场局势分析，合理调度‘附近的、合理数量的单位’，避免全图空防；当司令明确说‘所有人’，则默认仅调度所有‘可调用’旅长共同执行该战略（不可调用旅长不生成路由）。")
    parts.append("坐标约定：向旅长下达任务时，如已明确目的地或集结点，尽可能在 route.params 中附上坐标 {x,y}，例如 {center:{x,y}} 或 {target:{x,y}}；若无明确坐标：当任务为 attack 时，默认目标为敌方基地坐标。旅长的 route.task 必须是自然语言短句（中文），直接可读，不允许输出摘要或代码标签，例如：‘三旅长正面进攻至(Ex,Ey)’、‘二旅长沿左翼推进至(Ex-15,Ey)’，不同旅长必须给出不同的任务文本。")
    summary = _summarize_battlefield(battlefield or {})
    try:
        eb = summary.get("enemy_base") or {}
        ex = int(eb.get("x", 0)) if isinstance(eb, dict) else 0
        ey = int(eb.get("y", 0)) if isinstance(eb, dict) else 0
        observed = bool((battlefield or {}).get("enemy_base_observed"))
        label = f"敌方基地坐标：({ex},{ey})" + ("" if observed else "(缓存)")
        parts.append(label)
    except Exception:
        pass
    parts.append("强制分配规则：任何输入必须分解并分配给至少一个下级；根据战场情况可同时路由多个单位与角色；禁止返回空 routes。")
    parts.append("简化路由规则（LLM可直接套用的IF-THEN）：\n- 征兵部长联动：若意图偏向‘防御’，输出 {role:\"recruitment\",task:\"assign\",params:{reinforcements:{brigade:\"brigade_1\"}}}；若偏向‘进攻’，输出 {role:\"recruitment\",task:\"assign\",params:{reinforcements:{brigade:\"brigade_3\"}}}。当表达包含‘准备进攻’、‘集结进攻’、‘构筑防线’、‘准备防御’、‘防御部署’等同义词时，也视为进攻/防御并必须联动征兵部长，采用上述倾斜规则；若判断为‘大规模进攻/防御’，在旅长路由的同时强制联动征兵部长。\n- 后勤部长：当司令战略明确包含‘建造某个建筑’、‘构筑防线/防御设施’、‘生产作战单位’这类‘建造’项时，输出 {role:\"logistics\",task:\"build\"|\"defense_line\"|\"produce\",params:{...}}；其它（调遣/纯作战战略等）不向后勤部长下达命令。\n- 旅长优先：除‘建造/征兵’规则外的任务（进攻/防御/调遣集结/巡逻/侦察）均路由给旅长，结合旅长中心坐标与敌我基地坐标选择 brigade_1..brigade_4，并给出自然语言 task 文本（中文）与坐标 params；仅在必要时并发多个旅长。\n- 规模识别准则：当表达包含‘全线/全面/所有人/总攻/总防/大部队/大量’或发现‘基地遭受大规模入侵’等词，或局势显示敌方密度过高/我方主力需集中行动，则判定为‘大规模’。")
    parts.append("默认分配规范（进攻）：若司令仅说‘进攻/攻击’，且未明确‘所有人’，则：三旅长正面进攻目标为敌方基地(Ex,Ey)；二旅长从左翼推进，目标为(Ex-15,Ey)；四旅长从右翼推进，目标为(Ex+15,Ey)；一旅长待命观察。若明确提及‘所有人进攻’，则一旅长也正面进攻至(Ex,Ey)。每个旅长必须生成独立 route，且 route.task 为不同的自然语言短句。")
    parts.append("默认分配规范（防守）：若司令仅说‘防守/防御’，且未明确‘所有人’，则：一旅长驻守其辖区中心；二旅长在我方基地左侧( Ax-15, Ay ) 构筑/巡逻；四旅长与一旅长在我方基地中心( Ax, Ay ) 协同驻守；三旅长根据敌情可侦察或机动。每个旅长必须生成独立 route，且 route.task 为不同的自然语言短句。")
    parts.append("示例（进攻，未说明所有人）：routes 至少包含三条旅长路由并联动征兵（仅针对‘可调用旅长’，示例中的旅长代码需替换为当前可调用集合）：\n1) {role:\"brigade\", task:\"三旅长正面进攻至(Ex,Ey)\", params:{brigade:\"brigade_3\", target:{x:Ex,y:Ey}} }\n2) {role:\"brigade\", task:\"二旅长左翼推进至(Ex-15,Ey)\", params:{brigade:\"brigade_2\", target:{x:Ex-15,y:Ey}} }\n3) {role:\"brigade\", task:\"四旅长右翼推进至(Ex+15,Ey)\", params:{brigade:\"brigade_4\", target:{x:Ex+15,y:Ey}} }\n4) {role:\"recruitment\", task:\"assign\", params:{reinforcements:{brigade:\"brigade_3\"}} }\n注意：这是格式示例，不要求强制包含上述所有旅长；必须严格依据‘可调用旅长’集合输出。")
    parts.append("示例（防守，未说明所有人）：routes 至少三条并联动征兵（仅针对‘可调用旅长’，示例中的旅长代码需替换为当前可调用集合）：\n1) {role:\"brigade\", task:\"一旅长驻守辖区中心\", params:{brigade:\"brigade_1\", center:{x:C1x,y:C1y}} }\n2) {role:\"brigade\", task:\"二旅长在我方基地左侧守卫\", params:{brigade:\"brigade_2\", center:{x:Ax-15,y:Ay}} }\n3) {role:\"brigade\", task:\"四旅长在我方基地中心协同驻守\", params:{brigade:\"brigade_4\", center:{x:Ax,y:Ay}} }\n4) {role:\"recruitment\", task:\"assign\", params:{reinforcements:{brigade:\"brigade_1\"}} }\n注意：这是格式示例，不要求强制包含上述所有旅长；必须严格依据‘可调用旅长’集合输出。")
    
    parts.append("司令输入：" + str(input_text))
    try:
        parts.append("可用旅长：" + json.dumps(brigades_info or [], ensure_ascii=False))
    except Exception:
        parts.append("可用旅长：[]")
    try:
        sps = summary.get("special_points") or {}
        parts.append("地图特殊点位(JSON)：" + json.dumps(sps, ensure_ascii=False))
    except Exception:
        parts.append("地图特殊点位(JSON)：{}")
    try:
        centers_info = []
        for b in (brigades_info or []):
            c = (b or {}).get("center")
            if isinstance(c, dict) and "x" in c and "y" in c:
                centers_info.append({"brigade": b.get("code"), "center": {"x": int(c.get("x",0)), "y": int(c.get("y",0))}})
        if centers_info:
            parts.append("旅长中心(JSON)：" + json.dumps(centers_info, ensure_ascii=False))
    except Exception:
        pass
    # 敌我信息（英文代码+坐标）：敌方建筑、敌方单位、己方建筑
    try:
        parts.append("敌方建筑(JSON)：" + json.dumps(summary.get("enemy_buildings") or [], ensure_ascii=False))
    except Exception:
        parts.append("敌方建筑(JSON)：[]")
    try:
        parts.append("敌方单位(JSON)：" + json.dumps(summary.get("enemy_units") or [], ensure_ascii=False))
    except Exception:
        parts.append("敌方单位(JSON)：[]")
    try:
        parts.append("己方建筑(JSON)：" + json.dumps(summary.get("ally_buildings") or [], ensure_ascii=False))
    except Exception:
        parts.append("己方建筑(JSON)：[]")
    # 连队结构简表
    # 我方部队信息改为连队综述：连队名、单位数量、中心位置
    try:
        parts.append("连队综述(JSON)：" + json.dumps(summary.get("companies_overview") or [], ensure_ascii=False))
    except Exception:
        parts.append("连队综述(JSON)：[]")
    parts.append("输出要求（严格JSON）：仅输出一段可被 json.loads 解析的 JSON 字符串，格式为 {\"mode\":\"strategic\",\"routes\":[...],\"reason\":\"...\",\"report\":\"<一句执行情况汇报>\"}。routes 必须为合法 JSON 数组且在存在可分配任务时长度≥1；当意图涉及‘所有人’或多旅长并发，routes 必须为每个‘可调用旅长’分别生成一条独立 route（长度≥可调用旅长数量），且每项 params 必须包含 {brigade:\"brigade_#\"}；role 仅允许 \"brigade\"、\"logistics\"、\"recruitment\"；未触发征兵或后勤规则时不生成对应 role；禁止输出除上述键外的任何内容（无Markdown/解释/多余字段）。")
    parts.append("报告标准：report 不得复述司令原文，必须是一句独立简报，说明‘已下达给哪些角色’及‘关键倾斜/重点’，例如‘已下达：旅长3条，征兵倾斜第三战区，后勤建造2处’。禁止长段落与无意义复述。")
    s = "\n".join(parts)
    return s
