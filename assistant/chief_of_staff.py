from typing import Dict, Any, List

from .api_client import GameAPIClient, TargetsQueryParam
from .unit_mapping import UnitMapper
from .game_data_query import get_ally_combat_units, get_enemy_all_units


def _is_valid_unit(u_type: str) -> bool:
    """过滤掉无效单位（如出生点、残骸）"""
    t = str(u_type).lower()
    if "husk" in t or "残骸" in t or "mpspawn" in t:
        return False
    return True


class ChiefOfStaff:
    def __init__(self, api_client: GameAPIClient, unit_mapper: UnitMapper):
        self.api = api_client
        self.mapper = unit_mapper
        self.cache: Dict[str, Any] = {}
        self.has_started: bool = False

    def mark_started(self):
        self.has_started = True

    def snapshot(self) -> Dict[str, Any]:
        if not self.has_started:
            return dict(self.cache or {})
        try:
            base = self.api.player_base_info_query()
        except Exception:
            base = {}
        try:
            screen = self.api.screen_info_query()
        except Exception:
            screen = {}
        try:
            map_info = self.api.map_query()
        except Exception:
            map_info = {}
        try:
            allies = get_ally_combat_units(self.api, self.mapper)
        except Exception:
            allies = []
        try:
            enemies_raw = get_enemy_all_units(self.api, self.mapper)
            # 过滤残骸
            enemies = [e for e in enemies_raw if _is_valid_unit(e.get("type"))]
        except Exception:
            enemies = []
        ally_base = None
        enemy_base = None
        try:
            actors_ally = self.api.query_actor(TargetsQueryParam(faction="己方"))
        except Exception:
            actors_ally = []
        try:
            actors_enemy = self.api.query_actor(TargetsQueryParam(faction="敌方"))
            # 过滤残骸
            actors_enemy = [e for e in actors_enemy if _is_valid_unit(e.type)]
        except Exception:
            actors_enemy = []
        for a in actors_ally:
            c = self.mapper.get_code(a.type) or a.type
            if c == "fact" and a.position:
                ally_base = {"x": a.position.x, "y": a.position.y}
                break
        for e in actors_enemy:
            c = self.mapper.get_code(e.type) or e.type
            if c == "fact" and e.position:
                enemy_base = {"x": e.position.x, "y": e.position.y}
                break
        ally_building_counts: Dict[str, int] = {}
        ally_buildings: List[Dict[str, int]] = []
        enemy_buildings: List[Dict[str, int]] = []
        try:
            building_codes = {"fact","power","proc","barr","weap","dome","apwr","fix","afld","stek","ftur","tsla","sam"}
            for a in actors_ally:
                code = self.mapper.get_code(a.type) or a.type
                if code in building_codes:
                    ally_building_counts[code] = ally_building_counts.get(code, 0) + 1
                    if a.position:
                        ally_buildings.append({"type": code, "x": a.position.x, "y": a.position.y})
            for e in actors_enemy:
                code = self.mapper.get_code(e.type) or e.type
                if code in building_codes and e.position:
                    enemy_buildings.append({"type": code, "x": e.position.x, "y": e.position.y})
        except Exception:
            ally_building_counts = {}
            ally_buildings = []
            enemy_buildings = []
        queues: Dict[str, Any] = {}
        for qt in ["Building", "Defense", "Infantry", "Vehicle", "Aircraft"]:
            try:
                queues[qt] = self.api.query_production_queue(qt) or {}
            except Exception:
                queues[qt] = {}
        try:
            cp_resp = self.api.query_control_points() or {}
            control_points = cp_resp.get("controlPoints") or []
        except Exception:
            control_points = []
        defense_candidates = []
        try:
            bx = int((ally_base or {}).get("x", 0))
            by = int((ally_base or {}).get("y", 0))
            w = int(map_info.get("MapWidth") or map_info.get("width") or 128)
            h = int(map_info.get("MapHeight") or map_info.get("height") or 128)
            cand = [
                {"x": max(0, min(w - 1, bx)), "y": max(0, min(h - 1, by - 3)), "dir": "N"},
                {"x": max(0, min(w - 1, bx + 3)), "y": max(0, min(h - 1, by)), "dir": "E"},
                {"x": max(0, min(w - 1, bx)), "y": max(0, min(h - 1, by + 3)), "dir": "S"},
                {"x": max(0, min(w - 1, bx - 3)), "y": max(0, min(h - 1, by)), "dir": "W"},
            ]
            defense_candidates = cand
        except Exception:
            defense_candidates = []
        data = {
            "base": base,
            "screen": screen,
            "map": map_info,
            "allies": allies,
            "enemies": enemies,
            "ally_base": ally_base,
            "enemy_base": enemy_base,
            "ally_building_counts": ally_building_counts,
            "ally_buildings": ally_buildings,
            "enemy_buildings": enemy_buildings,
            "queues": queues,
            "control_points": control_points,
            "defense_candidates": defense_candidates,
        }
        try:
            self.cache = dict(data or {})
        except Exception:
            pass
        return data

    def snapshot_with_zones(self, brigades_info: List[Dict[str, Any]]) -> Dict[str, Any]:
        data = self.snapshot()
        zones: Dict[str, Any] = {}
        try:
            allies = data.get("allies") or []
            enemies = data.get("enemies") or []
            for b in (brigades_info or []):
                name = b.get("name") or ""
                bd = b.get("bounds") or {}
                x0 = int(bd.get("x0", 0)); y0 = int(bd.get("y0", 0)); x1 = int(bd.get("x1", 0)); y1 = int(bd.get("y1", 0))
                def in_bounds(x: int, y: int) -> bool:
                    return x >= x0 and x <= x1 and y >= y0 and y <= y1
                a_zone = [u for u in allies if in_bounds(int(u.get("x", 0)), int(u.get("y", 0)))]
                e_zone = [u for u in enemies if in_bounds(int(u.get("x", 0)), int(u.get("y", 0)))]
                cx = (x0 + x1) // 2
                cy = (y0 + y1) // 2
                nearest = None
                best = 10**9
                for e in e_zone:
                    ex = int(e.get("x", 0)); ey = int(e.get("y", 0))
                    d = abs(ex - cx) + abs(ey - cy)
                    if d < best:
                        best = d
                        nearest = {"id": e.get("id"), "type": e.get("type"), "x": ex, "y": ey, "distance": d}
                ac = len(a_zone)
                ec = len(e_zone)
                atypes: Dict[str, int] = {}
                etypes: Dict[str, int] = {}
                for u in a_zone:
                    t = str(u.get("type") or "")
                    atypes[t] = atypes.get(t, 0) + 1
                for u in e_zone:
                    t = str(u.get("type") or "")
                    etypes[t] = etypes.get(t, 0) + 1
                zones[name] = {"allies": a_zone, "enemies": e_zone, "bounds": bd, "summary": {"allies_count": ac, "enemies_count": ec, "allies_types": atypes, "enemies_types": etypes, "center": {"x": cx, "y": cy}, "nearest_enemy": nearest}}
        except Exception:
            zones = {}
        data["zones"] = zones
        return data

    def companies_overview(self, companies_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.has_started:
            return out
        try:
            comps = (companies_snapshot.get("companies") or {})
            for name, meta in comps.items():
                ids = list(meta.get("units") or [])
                cnt = len(ids)
                center = None
                try:
                    actors = self.api.query_actor(TargetsQueryParam(actorId=ids)) if ids else []
                    coords = [(a.position.x, a.position.y) for a in actors if getattr(a, 'position', None)]
                    if coords:
                        xs = sorted([x for x, _ in coords]); ys = sorted([y for _, y in coords])
                        mx = xs[len(xs)//2]; my = ys[len(ys)//2]
                        close = [(x, y) for (x, y) in coords if abs(x - mx) + abs(y - my) <= 10]
                        if close:
                            cx = sum(x for x, _ in close) // len(close)
                            cy = sum(y for _, y in close) // len(close)
                            center = {"x": cx, "y": cy}
                        else:
                            center = {"x": mx, "y": my}
                except Exception:
                    center = None
                if cnt > 0:
                    out.append({
                        "name": name,
                        "code": meta.get("code"),
                        "brigade": meta.get("brigade"),
                        "count": cnt,
                        "center": center
                    })
        except Exception:
            out = []
        return out
