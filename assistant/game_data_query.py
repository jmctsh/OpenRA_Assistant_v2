# -*- coding: utf-8 -*-
"""
实时游戏数据查询模块
- 获取己方作战单位（排除建筑、防御、矿车、MCV）
- 获取敌方所有单位（包括作战单位、建筑、防御、矿车、MCV）
- 转换为LLM友好的JSON格式
"""
from typing import List, Dict, Any
from .api_client import GameAPIClient, TargetsQueryParam, Actor
from .unit_mapping import UnitMapper


def get_ally_combat_units(api_client: GameAPIClient, unit_mapper: UnitMapper) -> List[Dict[str, Any]]:
    """
    获取己方作战单位列表（排除建筑、防御、矿车、MCV）
    返回格式: [{"id": int, "type": str, "x": int, "y": int}, ...]
    """
    try:
        # 查询己方所有单位
        all_allies = api_client.query_actor(TargetsQueryParam(faction="己方"))
        
        # 定义非作战单位集合（使用小写做判定）
        non_combat_codes = {
            # 建筑
            "fact", "power", "barr", "proc", "weap", "dome", "apwr", "fix", "afld", 
            "stek", "tent", "kenn", "hpad", "spen", "syrd", "atek",
            # 防御
            "ftur", "tsla", "sam", "silo", "gun", "agun", "pbox", "hbox", "gap", "iron", "pdox", "mslo",
            # 非作战单位
            "harv",    # 矿车
            "mcv",     # 基地车
            "mpspawn", # 出生点（不可攻击）
            "camera"    # 摄像机/无关实体
        }
        
        combat_units = []
        for actor in all_allies:
            if not actor.position:
                continue
                
            # 获取单位英文代码
            unit_code = unit_mapper.get_code(actor.type) or actor.type
            unit_code_l = str(unit_code).lower()
            
            # 过滤掉非作战单位（含 camera），大小写不敏感
            if unit_code_l not in non_combat_codes:
                item = {
                    "id": actor.actor_id,
                    "type": unit_code,
                    "x": actor.position.x,
                    "y": actor.position.y
                }
                try:
                    if getattr(actor, 'hp', None) is not None:
                        item["hp"] = actor.hp
                    if getattr(actor, 'max_hp', None) is not None:
                        item["maxHp"] = actor.max_hp
                except Exception:
                    pass
                combat_units.append(item)
        
        return combat_units
    except Exception:
        return []


def get_enemy_all_units(api_client: GameAPIClient, unit_mapper: UnitMapper) -> List[Dict[str, Any]]:
    """
    获取敌方所有单位列表（包括作战单位、建筑、防御、矿车、MCV）
    返回格式: [{"id": int, "type": str, "x": int, "y": int, "hp"?: int, "maxHp"?: int}, ...]
    """
    try:
        # 查询敌方所有单位
        all_enemies = api_client.query_actor(TargetsQueryParam(faction="敌方"))
        
        enemy_units = []
        for actor in all_enemies:
            if not actor.position:
                continue
                
            # 获取单位英文代码
            unit_code = unit_mapper.get_code(actor.type) or actor.type
            unit_code_l = str(unit_code).lower()
            
            # 过滤掉出生点和无关实体（camera），大小写不敏感
            if unit_code_l in ("mpspawn", "camera"):
                continue
            
            item = {
                "id": actor.actor_id,
                "type": unit_code,  # 使用英文代码
                "x": actor.position.x,
                "y": actor.position.y
            }
            # 仅在可用时提供血量信息，避免误判
            if actor.hp is not None:
                item["hp"] = actor.hp
            if actor.max_hp is not None:
                item["maxHp"] = actor.max_hp
            
            enemy_units.append(item)
        
        return enemy_units
    except Exception:
        return []


def build_llm_prompt_data(ally_units: List[Dict[str, Any]], enemy_units: List[Dict[str, Any]]) -> str:
    """
    构建LLM输入数据字符串
    格式：JSON字符串，包含己方作战单位和敌方所有单位信息
    """
    data = {
        "ally_combat_units": ally_units,
        "enemy_all_units": enemy_units
    }
    
    import json
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
