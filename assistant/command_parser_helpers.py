# -*- coding: utf-8 -*-
"""
OpenRA 助手程序 - 命令解析器辅助方法

这个模块包含检查命令相关的辅助方法。
"""

import time
from typing import List, Dict, Any
from .api_client import GameAPIClient, TargetsQueryParam
from .unit_mapping import UnitMapper


def handle_unified_overview_query(api_client: GameAPIClient, unit_mapper: UnitMapper, faction: str, map_cache: Dict[str, Any] = None) -> Dict[str, Any]:
    """统一处理建筑和单位查询，返回所有类型的结果，与API返回保持一致"""
    try:
        # 直接查询指定派系的所有actor（建筑+单位）
        all_actors = api_client.query_actor(TargetsQueryParam(faction=faction))
        
        # 如果API查询有结果且是敌方，更新缓存
        if all_actors and faction == "敌方" and map_cache is not None:
            # 分离建筑和单位，更新对应缓存
            buildings_cache = {}
            units_cache = {}
            saw_enemy_base = False
            
            building_codes = {"fact", "power", "barr", "proc", "weap", "dome", "apwr", "fix", "afld", "stek", "ftur", "tsla", "sam"}
            
            for actor in all_actors:
                if not actor.position:
                    continue
                    
                actor_code = unit_mapper.get_code(actor.type) if actor.type else actor.type
                
                if actor_code in building_codes:
                    # 这是建筑
                    if actor_code in {"fact"}:
                        # 基地特殊处理
                        new_base_pos = {"x": actor.position.x, "y": actor.position.y}
                        print(f"DEBUG: handle_unified_overview_query发现敌方基地 {actor.type}(code:{actor_code}) 位置: {new_base_pos}")
                        map_cache["last_enemy_base"] = new_base_pos
                        map_cache["enemy_base_real_observed"] = True
                        map_cache["estimated_enemy_base"] = None  # 清除预估值
                        saw_enemy_base = True
                    else:
                        # 其他建筑
                        pos = {"x": actor.position.x, "y": actor.position.y, "last_seen": int(time.time() * 1000)}
                        buildings_cache.setdefault(actor_code, []).append(pos)
                else:
                    # 这是单位
                    units_cache[actor.type] = units_cache.get(actor.type, 0) + 1
            
            # 更新缓存
            if buildings_cache:
                map_cache["enemy_buildings"] = buildings_cache
            if units_cache:
                map_cache["enemy_units_overview"] = {
                    "last_seen": int(time.time() * 1000),
                    "stats": units_cache
                }
        
        # 如果API查询为空，尝试从缓存获取（仅限敌方）
        if not all_actors and faction == "敌方" and map_cache:
            cached_actors = []
            actor_stats = {}
            
            # 从建筑缓存中获取
            building_cache = map_cache.get("enemy_buildings", {})
            for building_code, positions in building_cache.items():
                type_name = unit_mapper.get_primary_name(building_code) or building_code
                if building_code not in actor_stats:
                    actor_stats[building_code] = {"count": 0, "type_name": type_name}
                
                for pos_data in positions:
                    if isinstance(pos_data, dict) and "x" in pos_data and "y" in pos_data:
                        actor_stats[building_code]["count"] += 1
                        cached_actors.append({
                            "type": building_code,
                            "type_name": type_name,
                            "position": {"x": pos_data["x"], "y": pos_data["y"]},
                            "hp": None,
                            "max_hp": None,
                            "actor_id": None,
                            "source": "cache",
                            "last_seen": pos_data.get("last_seen")
                        })
            
            # 从基地缓存中获取
            cached_base = map_cache.get("last_enemy_base")
            if cached_base and isinstance(cached_base, dict) and "x" in cached_base and "y" in cached_base:
                type_name = unit_mapper.get_primary_name("fact") or "基地"
                if "fact" not in actor_stats:
                    actor_stats["fact"] = {"count": 0, "type_name": type_name}
                actor_stats["fact"]["count"] += 1
                cached_actors.append({
                    "type": "fact",
                    "type_name": type_name,
                    "position": {"x": cached_base["x"], "y": cached_base["y"]},
                    "hp": None,
                    "max_hp": None,
                    "actor_id": None,
                    "source": "cache"
                })
            
            # 从单位缓存中获取
            units_overview = map_cache.get("enemy_units_overview", {})
            if units_overview and isinstance(units_overview, dict):
                unit_stats = units_overview.get("stats", {})
                for unit_type, count in unit_stats.items():
                    type_name = unit_mapper.get_primary_name(unit_type) or unit_type
                    if unit_type not in actor_stats:
                        actor_stats[unit_type] = {"count": 0, "type_name": type_name}
                    actor_stats[unit_type]["count"] += count
                    
                    # 为单位创建虚拟条目（无位置信息）
                    for _ in range(count):
                        cached_actors.append({
                            "type": unit_type,
                            "type_name": type_name,
                            "position": None,
                            "hp": None,
                            "max_hp": None,
                            "actor_id": None,
                            "source": "cache"
                        })
            
            if cached_actors:
                overview_message = f"{faction}概览（基于缓存）:\n"
                total_count = sum(stats["count"] for stats in actor_stats.values())
                for actor_type, stats in actor_stats.items():
                    overview_message += f"- {stats['type_name']}: {stats['count']}个\n"
                
                return {
                    "success": True,
                    "message": overview_message.strip(),
                    "data": {
                        "faction": faction,
                        "total_count": total_count,
                        "actor_stats": actor_stats,
                        "actors": cached_actors,
                        "from_cache": True
                    }
                }
        
        if not all_actors:
            return {"success": True, "message": f"未发现{faction}单位或建筑", "data": {"actors": [], "total_count": 0}}
        
        # 按类型分组统计
        actor_stats = {}
        total_count = 0
        actor_list = []
        
        for actor in all_actors:
            type_name = unit_mapper.get_primary_name(actor.type) or actor.type
            if actor.type not in actor_stats:
                actor_stats[actor.type] = {
                    "count": 0,
                    "type_name": type_name
                }
            
            actor_stats[actor.type]["count"] += 1
            total_count += 1
            
            actor_list.append({
                "type": actor.type,
                "type_name": type_name,
                "position": {"x": actor.position.x, "y": actor.position.y} if actor.position else None,
                "hp": actor.hp,
                "max_hp": actor.max_hp,
                "actor_id": actor.actor_id,
                "source": "api"
            })
        
        # 生成概览信息
        overview_message = f"{faction}概览:\n"
        for actor_type, stats in actor_stats.items():
            overview_message += f"- {stats['type_name']}: {stats['count']}个\n"
        
        return {
            "success": True,
            "message": overview_message.strip(),
            "data": {
                "faction": faction,
                "total_count": total_count,
                "actor_stats": actor_stats,
                "actors": actor_list,
                "from_cache": False
            }
        }
        
    except Exception as e:
        return {"success": False, "message": f"查询{faction}概览时出错: {str(e)}"}


def handle_building_position_query(api_client: GameAPIClient, unit_mapper: UnitMapper, building_types: List[str], faction: str, map_cache: Dict[str, Any]) -> Dict[str, Any]:
    """处理建筑位置查询"""
    try:
        if not building_types:
            return {"success": False, "message": "未指定要查询的建筑类型"}
        
        base_like = {"fact"}
        is_base_query = any(bt in base_like for bt in building_types)
        
        # 优先使用缓存中的位置信息（仅敌方或基地查询）
        if faction == "敌方" or is_base_query:
            position_info = []
            
            # 基地查询的缓存优先逻辑
            if is_base_query:
                cached_base = None
                hint_tag = "缓存"
                if faction == "己方":
                    cached_base = map_cache.get("last_ally_base")
                elif faction == "敌方":
                    # 优先真实缓存，其次预估
                    cached_base = map_cache.get("last_enemy_base") or map_cache.get("estimated_enemy_base")
                    hint_tag = "缓存" if map_cache.get("last_enemy_base") else "预估"
                
                if isinstance(cached_base, dict) and "x" in cached_base and "y" in cached_base:
                    type_name = unit_mapper.get_primary_name("fact") or "基地"
                    position_info = [{
                        "type": "fact",
                        "type_name": type_name,
                        "position": {"x": cached_base["x"], "y": cached_base["y"]},
                        "hp": None,
                        "max_hp": None,
                        "actor_id": None,
                        "source": "cache" if hint_tag == "缓存" else "estimated"
                    }]
                    msg = f"找到{faction}{type_name}（{hint_tag}），位置: ({cached_base['x']}, {cached_base['y']})"
                    return {
                        "success": True,
                        "message": msg,
                        "data": {
                            "faction": faction,
                            "building_types": building_types,
                            "buildings": position_info,
                            "from_cache": True
                        }
                    }
            
            # 非基地建筑的缓存查询（仅敌方）
            if faction == "敌方" and not is_base_query:
                for bt in building_types:
                    cached = map_cache.get("enemy_buildings", {}).get(bt, [])
                    for item in cached:
                        if isinstance(item, dict) and "x" in item and "y" in item:
                            type_name = unit_mapper.get_primary_name(bt) or bt
                            position_info.append({
                                "type": bt,
                                "type_name": type_name,
                                "position": {"x": item["x"], "y": item["y"]},
                                "hp": None,
                                "max_hp": None,
                                "actor_id": None,
                                "source": "cache",
                                "last_seen": item.get("last_seen")
                            })
                
                # 如果从缓存拿到了数据，就返回
                if position_info:
                    if len(position_info) == 1:
                        info = position_info[0]
                        msg = f"找到{faction}{info['type_name']}（缓存），位置: ({info['position']['x']}, {info['position']['y']})"
                    else:
                        msg = f"基于缓存找到{len(position_info)}个{faction}建筑:\n"
                        for info in position_info:
                            msg += f"- {info['type_name']}: ({info['position']['x']}, {info['position']['y']})\n"
                        msg = msg.strip()
                    return {
                        "success": True,
                        "message": msg,
                        "data": {
                            "faction": faction,
                            "building_types": building_types,
                            "buildings": position_info,
                            "from_cache": True
                        }
                    }
        
        # 缓存中没有数据，尝试API查询
        building_names = [unit_mapper.get_primary_name(bt) or bt for bt in building_types]
        buildings = api_client.query_actor(TargetsQueryParam(type=building_names, faction=faction))
        
        # 仅当API查询到基地时才更新缓存（防止空值覆盖）
        if buildings and is_base_query:
            for building in buildings:
                # 确保查询到的建筑类型确实是基地类型
                building_code = unit_mapper.get_code(building.type) if building.type else None
                if building.position and building_code in base_like:
                    pos = {"x": building.position.x, "y": building.position.y}
                    if faction == "己方":
                        map_cache["last_ally_base"] = pos
                        print(f"DEBUG: 手动查询更新己方基地缓存: {pos}")
                    elif faction == "敌方":
                        print(f"DEBUG: 手动查询发现敌方基地 {building.type}(code:{building_code}) 位置: {pos}")
                        map_cache["last_enemy_base"] = pos
                        map_cache["enemy_base_real_observed"] = True
                        # 清除过时的预估值
                        map_cache["estimated_enemy_base"] = None
                        print(f"DEBUG: 手动查询更新敌方基地真实缓存: {pos}")
                    break  # 只更新第一个找到的基地
        
        # 如果敌方且API没有返回，尝试使用缓存（非基地类建筑）
        if (not buildings) and faction == "敌方":
            position_info = []
            for bt in building_types:
                cached = map_cache.get("enemy_buildings", {}).get(bt, [])
                for item in cached:
                    pos = {"x": item.get("x"), "y": item.get("y")}
                    if isinstance(item, dict) and "x" in item and "y" in item:
                        type_name = unit_mapper.get_primary_name(bt) or bt
                        position_info.append({
                            "type": bt,
                            "type_name": type_name,
                            "position": pos,
                            "hp": None,
                            "max_hp": None,
                            "actor_id": None,
                            "source": "cache",
                            "last_seen": item.get("last_seen")
                        })
            # 如果从缓存拿到了数据，就返回
            if position_info:
                if len(position_info) == 1:
                    info = position_info[0]
                    msg = f"找到{faction}{info['type_name']}（缓存），位置: ({info['position']['x']}, {info['position']['y']})"
                else:
                    msg = f"基于缓存找到{len(position_info)}个{faction}建筑:\n"
                    for info in position_info:
                        msg += f"- {info['type_name']}: ({info['position']['x']}, {info['position']['y']})\n"
                    msg = msg.strip()
                return {
                    "success": True,
                    "message": msg,
                    "data": {
                        "faction": faction,
                        "building_types": building_types,
                        "buildings": position_info,
                        "from_cache": True
                    }
                }
        
        if not buildings:
            building_names = [unit_mapper.get_primary_name(bt) or bt for bt in building_types]
            # 兜底：针对基地/工厂类给出可能的基地位置提示
            extra_hint = ""
            base_like = {"fact"}
            if faction == "敌方" and any(bt in base_like for bt in building_types):
                enemy_base = map_cache.get("last_enemy_base")
                if enemy_base and isinstance(enemy_base, dict) and "x" in enemy_base and "y" in enemy_base:
                    extra_hint = f"（最近发现的敌方基地大致在: ({enemy_base['x']}, {enemy_base['y']})）"
            if faction == "己方" and any(bt in base_like for bt in building_types):
                ally_base = map_cache.get("last_ally_base")
                if ally_base and isinstance(ally_base, dict) and "x" in ally_base and "y" in ally_base:
                    extra_hint = f"（己方基地在: ({ally_base['x']}, {ally_base['y']})）"
            return {"success": True, "message": f"未发现{faction}的{'/'.join(building_names)}{extra_hint}", "data": {"buildings": []}}
        
        # 整理建筑位置信息
        position_info = []
        for building in buildings:
            if building.position:
                type_name = unit_mapper.get_primary_name(building.type) or building.type
                position_info.append({
                    "type": building.type,
                    "type_name": type_name,
                    "position": {"x": building.position.x, "y": building.position.y},
                    "hp": building.hp,
                    "max_hp": building.max_hp,
                    "actor_id": building.actor_id
                })
        
        # 生成位置信息消息
        if len(position_info) == 1:
            info = position_info[0]
            message = f"找到{faction}{info['type_name']}，位置: ({info['position']['x']}, {info['position']['y']})"
        else:
            message = f"找到{len(position_info)}个{faction}建筑:\n"
            for info in position_info:
                message += f"- {info['type_name']}: ({info['position']['x']}, {info['position']['y']})\n"
            message = message.strip()
        
        return {
            "success": True,
            "message": message,
            "data": {
                "faction": faction,
                "building_types": building_types,
                "buildings": position_info,
                "from_cache": False
            }
        }
        
    except Exception as e:
        return {"success": False, "message": f"查询{faction}建筑位置时出错: {str(e)}"}