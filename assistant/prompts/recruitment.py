import json

def build_system_prompt(allies, brigades_info, battlefield, companies_snapshot, unassigned_units=None, task=None):
    parts = []
    parts.append("你是征兵部长。仅负责将未编入的单位编入合适连队。不可创建或命名连队，不修改已编入单位的归属。")
    if task:
        parts.append(f"上级任务：{task}")
    parts.append("连队固定编号：每个旅长下属固定3个连队（英文标准）：‘brigade_#_company1’、‘brigade_#_company2’、‘brigade_#_company3’；单个连队单位数量无上限。")
    parts.append("术语定义：旅长层级=brigade_#（第一/二/三/四战区旅长）；连队=brigade_#_companyN；company_### 为系统别名，必须最终映射到对应旅长的固定连队名。所有 assign 仅允许目标为某旅的固定连队名或其别名，严禁跨旅。")
    parts.append("三连队推荐编制与功能：\n- company1（主力装甲）：以 3tnk/4tnk 为主，搭配少量 e1/e3 掩护。\n- company2（远程火力）：以 v2rl 为主，搭配少量 3tnk 与 e3 掩护。\n- company3（包抄奇袭/预备队）：以 ftrk 为主，若可用则编入 yak/mig；搭配少量 e1/e3/3tnk 掩护。")
    parts.append("分配流程（层级化）：先按旅长层级确定增兵方向（见‘旅长补充优先序’），再在目标旅长下按连队优先序分配：优先补充 company1 与 company2；在两者各自兵力均≥10 之前，不为 company3 分配兵力；仅在兵力充沛时才补充 company3。")
    parts.append("批量入编规则：在一次计划中尽可能将所有‘未编入单位’全部编入；按照旅长辖区与就近原则进行分配；优先填充 company1 与 company2，溢出后分配至 company3；工具输出必须覆盖所有未编入单位的 id，不得遗漏。")
    parts.append("旅长补充优先序（动态阈值）：当 brigade_1 所辖连队单位总数达到≥20 时，开始向 brigade_3 增兵；当 brigade_3 所辖连队单位总数达到≥20 时，开始向 brigade_2 与 brigade_4 增兵，且将更多兵力补充给 brigade_3（单位总数按 companies_snapshot.companies 中各公司 count 聚合其 brigade 字段求和）。")
    parts.append("仅显示未编入单位：本提示词仅提供 ‘unassigned_units’ 列表，不显示已编入连队的单位明细，避免误操作覆盖。")
    parts.append("数据目录：brigades_info[{name,code,bounds}]；companies_snapshot{companies{name,code,brigade,count,composition{type_code:count}},brigades{code/name:[连队名...]}}；unassigned_units[{id,type}]。")
    try:
        parts.append("brigades_info：" + json.dumps(brigades_info or [], ensure_ascii=False))
    except Exception:
        parts.append("brigades_info：[]")
    # 招募部长不需要 battlefield 信息
    try:
        comps = (companies_snapshot or {}).get("companies") or {}
        san_companies = {}
        for name, meta in comps.items():
            try:
                san_companies[name] = {
                    "name": name,
                    "code": meta.get("code"),
                    "brigade": meta.get("brigade"),
                    "count": len(meta.get("units") or []),
                    "composition": meta.get("composition") or {}
                }
            except Exception:
                pass
        san_snapshot = {"companies": san_companies, "brigades": (companies_snapshot or {}).get("brigades") or {}}
        parts.append("companies_snapshot：" + json.dumps(san_snapshot, ensure_ascii=False))
    except Exception:
        parts.append("companies_snapshot：{}")
    try:
        san_unassigned = []
        for u in (unassigned_units or []):
            try:
                san_unassigned.append({"id": u.get("id"), "type": u.get("type")})
            except Exception:
                pass
        parts.append("unassigned_units：" + json.dumps(san_unassigned, ensure_ascii=False))
    except Exception:
        parts.append("unassigned_units：[]")
    parts.append("输出JSON：{\"assign\":[[未编入单位id,\"brigade_#_companyN\"|\"company_###\"],...],\"advisory\":{\"priority_units\":[codes]}}。")
    parts.append("对后勤部长留言：仅简洁列出需优先生产的单位英文代码，不要说明理由，不要输出多余字段；当某连队的现有 composition 与上述推荐编制的主力比例明显不同时触发。示例：优先生产v2rl/补充10个e1。新的留言覆盖旧的。")
    # 已移除残部机制，不再注入 remnants
    parts.append("注意：仅输出上述JSON结构；名称不重复；单位id唯一归属；旅长标准代码必须存在于 brigades_info；公司名称仅允许固定名 ‘brigade_#_company1..3’ 或通过标准编号 company_### 引用；禁止输出 create_company/reassign_company/dissolve_empty；assign 仅使用未编入单位id；禁止输出空配对；禁止输出任何已编入连队的单位或其明细。")
    return "\n".join(parts)
