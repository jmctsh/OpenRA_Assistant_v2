# -*- coding: utf-8 -*-
"""
OpenRA 助手程序 - API客户端

这个模块负责与OpenRA游戏进行通信，提供了一系列方法来发送指令和接收游戏状态。
所有的通信都是通过socket连接完成的。
"""

import socket
import json
import time
import uuid
from typing import List, Dict, Any, Optional, Tuple
from .unit_mapping import UnitMapper

# API版本常量
API_VERSION = "1.0"


class GameAPIError(Exception):
    """游戏API异常基类"""
    def __init__(self, code: str, message: str, details: Dict = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")


class Location:
    """位置类，表示游戏中的坐标"""
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def to_dict(self):
        return {"x": self.x, "y": self.y}


class Actor:
    """单位类，表示游戏中的单位"""
    def __init__(self, actor_id: int, type: str = None, faction: str = None, position: Location = None, hp: int = None, max_hp: int = None, is_dead: bool = False):
        self.actor_id = actor_id
        self.type = type
        self.faction = faction
        self.position = position
        self.hp = hp
        self.max_hp = max_hp
        self.is_dead = is_dead


class TargetsQueryParam:
    """目标查询参数类，用于查询符合条件的单位"""
    def __init__(self, type: List[str] = None, faction: str = None, range: str = "all", restrain: List[dict] = None, actorId: List[int] = None):
        self.type = type or []
        self.faction = faction
        self.range = range
        self.restrain = restrain or []
        self.actorId = actorId or []

    def to_dict(self):
        result = {
            "type": self.type,
            "faction": self.faction,
            "range": self.range,
            "restrain": self.restrain
        }
        if self.actorId:
            result["actorId"] = self.actorId
        return result


class GameAPIClient:
    """游戏API客户端类，用于与游戏服务器进行通信"""
    MAX_RETRIES = 1
    RETRY_DELAY = 0.5

    # ===== 依赖关系表（已废弃，交由游戏引擎判定）=====
    BUILDING_DEPENDENCIES: Dict[str, list] = {}

    UNIT_DEPENDENCIES: Dict[str, list] = {}

    @staticmethod
    def is_server_running(host="localhost", port=7445, timeout=2.0) -> bool:
        '''检查游戏服务器是否已启动并可访问

        Args:
            host (str): 游戏服务器地址，默认为"localhost"。
            port (int): 游戏服务器端口，默认为 7445。
            timeout (float): 连接超时时间（秒），默认为 2.0 秒。

        Returns:
            bool: 服务器是否已启动并可访问
        '''
        try:
            request_data = {
                "apiVersion": API_VERSION,
                "requestId": str(uuid.uuid4()),
                "command": "ping",
                "params": {},
                "language": "zh"
            }

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((host, port))

                # 发送请求
                json_data = json.dumps(request_data)
                sock.sendall(json_data.encode('utf-8'))

                # 接收响应
                chunks = []
                while True:
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    except socket.timeout:
                        if chunks:
                            break
                        return False

                data = b''.join(chunks).decode('utf-8')

                try:
                    response = json.loads(data)
                    if response.get("status", 0) > 0 and "data" in response:
                        return True
                    return False
                except json.JSONDecodeError:
                    return False

        except (socket.error, ConnectionRefusedError, OSError):
            return False

        except Exception:
            return False

    def __init__(self, host="localhost", port=7445, language="zh"):
        self.server_address = (host, port)
        self.language = language
        # 用于在查询阶段统一名称到英文代码（并对少数特例改回中文）
        self._unit_mapper = UnitMapper()

    def _generate_request_id(self) -> str:
        """生成唯一的请求ID"""
        return str(uuid.uuid4())

    def _send_request(self, command: str, params: dict) -> dict:
        '''通过socket和Game交互，发送信息并接收响应

        Args:
            command (str): 要执行的命令
            params (dict): 命令相关的数据参数

        Returns:
            dict: 服务器返回的JSON响应数据

        Raises:
            GameAPIError: 当API调用出现错误时
            ConnectionError: 当连接服务器失败时
        '''
        request_id = self._generate_request_id()
        request_data = {
            "apiVersion": API_VERSION,
            "requestId": request_id,
            "command": command,
            "params": params,
            "language": self.language
        }

        retries = 0
        while retries < self.MAX_RETRIES:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)  # 设置超时时间
                    sock.connect(self.server_address)

                    # 发送请求
                    json_data = json.dumps(request_data)
                    sock.sendall(json_data.encode('utf-8'))

                    # 接收响应
                    response_data = self._receive_data(sock)

                    try:
                        response = json.loads(response_data)

                        # 验证响应格式
                        if not isinstance(response, dict):
                            raise GameAPIError("INVALID_RESPONSE", "服务器返回的响应格式无效")

                        # 检查请求ID匹配
                        if response.get("requestId") != request_id:
                            raise GameAPIError("REQUEST_ID_MISMATCH", "响应的请求ID不匹配")

                        # 处理错误响应
                        if response.get("status", 0) < 0:
                            error = response.get("error", {})
                            raise GameAPIError(
                                error.get("code", "UNKNOWN_ERROR"),
                                error.get("message", "未知错误"),
                                error.get("details")
                            )

                        return response

                    except json.JSONDecodeError:
                        raise GameAPIError("INVALID_JSON", "服务器返回的不是有效的JSON格式")

            except (socket.timeout, ConnectionError) as e:
                retries += 1
                if retries >= self.MAX_RETRIES:
                    raise GameAPIError("CONNECTION_ERROR", f"连接服务器失败: {str(e)}")
                time.sleep(self.RETRY_DELAY)

            except GameAPIError:
                raise

            except Exception as e:
                raise GameAPIError("UNEXPECTED_ERROR", f"发生未预期的错误: {str(e)}")

    def _receive_data(self, sock: socket.socket) -> str:
        """从socket接收完整的响应数据"""
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except socket.timeout:
                if not chunks:
                    raise GameAPIError("TIMEOUT", "接收响应超时")
                break
        return b''.join(chunks).decode('utf-8')

    def _handle_response(self, response: dict) -> Any:
        """处理API响应，提取所需数据或抛出异常"""
        if response is None:
            raise GameAPIError("NO_RESPONSE", "响应为空")
        return response.get("data") if "data" in response else response

    # ===== 游戏API方法 =====

    def ping(self) -> Dict[str, Any]:
        """发送ping请求，检测服务器状态"""
        response = self._send_request("ping", {})
        return response.get("data", {})

    def player_base_info_query(self) -> Dict[str, Any]:
        """查询玩家基地信息"""
        try:
            response = self._send_request("player_baseinfo_query", {})
            result = self._handle_response(response)
            # 统一规范化字段：兼容大写/小写与嵌套power结构
            data = result if isinstance(result, dict) else {}
            if data is None:
                data = {}
            # 小写别名
            if "Cash" in data and "cash" not in data:
                data["cash"] = data.get("Cash", 0)
            if "Resources" in data and "ore" not in data:
                data["ore"] = data.get("Resources", 0)
            # 嵌套power结构提供provided/drained
            if ("PowerProvided" in data or "PowerDrained" in data):
                power = data.get("power") or {}
                if not isinstance(power, dict):
                    power = {}
                if "provided" not in power:
                    power["provided"] = data.get("PowerProvided", power.get("provided", 0))
                if "drained" not in power:
                    power["drained"] = data.get("PowerDrained", power.get("drained", 0))
                data["power"] = power
            return data
        except GameAPIError:
            raise
        except Exception as e:
            raise GameAPIError("BASE_INFO_QUERY_ERROR", f"查询玩家基地信息时发生错误: {str(e)}")

    def screen_info_query(self) -> Dict[str, Any]:
        """查询屏幕信息"""
        try:
            response = self._send_request("screen_info_query", {})
            result = self._handle_response(response)
            return result if result is not None else {}
        except GameAPIError:
            raise
        except Exception as e:
            raise GameAPIError("SCREEN_INFO_QUERY_ERROR", f"查询屏幕信息时发生错误: {str(e)}")

    def map_query(self) -> Dict[str, Any]:
        """查询地图信息"""
        response = self._send_request("map_query", {})
        data = response.get("data", {})
        
        # 规范化字段名，确保兼容不同的API响应格式
        if "MapWidth" in data and "width" not in data:
            data["width"] = data["MapWidth"]
        if "MapHeight" in data and "height" not in data:
            data["height"] = data["MapHeight"]
        
        return data

    def query_control_points(self) -> Dict[str, Any]:
        """查询当前地图上的据点及其Buff信息"""
        try:
            response = self._send_request("query_control_points", {})
            result = self._handle_response(response)
            if result is None:
                return {"controlPoints": []}
            if isinstance(result, dict):
                cps = result.get("controlPoints", [])
                if cps is None:
                    cps = []
                return {"controlPoints": cps}
            return {"controlPoints": []}
        except GameAPIError:
            raise
        except Exception as e:
            raise GameAPIError("QUERY_CONTROL_POINTS_ERROR", f"查询据点信息时发生错误: {str(e)}")

    def query_actor(self, query_params: TargetsQueryParam) -> List[Actor]:
        """查询符合条件的单位"""
        try:
            # 统一处理查询中的类型：将中文/同义词映射为英文代码，但对少数特例改为中文
            params_dict = query_params.to_dict()
            raw_types = params_dict.get("type", []) or []
            if raw_types:
                params_dict["type"] = self._normalize_query_types_for_engine(raw_types)
            params = {"targets": params_dict}
            response = self._send_request("query_actor", params)
            result = self._handle_response(response)
            
            actors = []
            actors_data = result.get("actors", []) if result else []
            
            for actor_data in actors_data:
                try:
                    position = Location(
                        actor_data["position"]["x"],
                        actor_data["position"]["y"]
                    ) if "position" in actor_data else None
                    
                    actor = Actor(
                        actor_id=actor_data["id"],
                        type=actor_data.get("type"),
                        faction=actor_data.get("faction"),
                        position=position,
                        hp=actor_data.get("hp"),
                        max_hp=actor_data.get("maxHp"),
                        is_dead=actor_data.get("isDead", False)
                    )
                    actors.append(actor)
                except KeyError as e:
                    raise GameAPIError("INVALID_ACTOR_DATA", f"Actor数据格式无效: {str(e)}")
            
            return actors
        except GameAPIError:
            raise
        except Exception as e:
            raise GameAPIError("QUERY_ACTOR_ERROR", f"查询Actor时发生错误: {str(e)}")

    def move_units_by_location(self, actors: List[Actor], location: Location, attack_move: bool = False, assault_move: bool = False) -> None:
        """移动单位到指定位置"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            },
            "location": location.to_dict(),
            "isAttackMove": 1 if attack_move else 0
        }
        if assault_move:
            params["isAssaultMove"] = 1
        self._send_request("move_actor", params)

    def move_units_by_direction(self, actors: List[Actor], direction: str, distance: int, attack_move: bool = False, assault_move: bool = False) -> None:
        """按方向移动单位"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            },
            "direction": direction,
            "distance": distance,
            "isAttackMove": 1 if attack_move else 0
        }
        if assault_move:
            params["isAssaultMove"] = 1
        self._send_request("move_actor", params)

    def attack_target(self, attacker: Actor, target: Actor) -> bool:
        """攻击目标"""
        params = {
            "attackers": {
                "actorId": [attacker.actor_id]
            },
            "targets": {
                "actorId": [target.actor_id]
            }
        }
        response = self._send_request("attack", params)
        # 服务器在成功时可能返回 {status:1, data: None}
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(response, dict) and response.get("status", 0) == 1:
            return True
        if isinstance(data, dict) and data.get("success") is True:
            return True
        return False

    def attack_targets(self, attackers: List[Actor], targets: List[Actor]) -> bool:
        """多单位攻击多目标"""
        params = {
            "attackers": {
                "actorId": [actor.actor_id for actor in attackers]
            },
            "targets": {
                "actorId": [target.actor_id for target in targets]
            }
        }
        response = self._send_request("attack", params)
        # 服务器在成功时可能返回 {status:1, data: None}
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(response, dict) and response.get("status", 0) == 1:
            return True
        if isinstance(data, dict) and data.get("success") is True:
            return True
        return False

    def occupy_targets(self, attackers: List[Actor], targets: List[Actor]) -> bool:
        """多单位与目标进行占用/进驻交互（如矿车交矿、飞机返航换弹）"""
        params = {
            "attackers": {
                "actorId": [actor.actor_id for actor in attackers]
            },
            "targets": {
                "actorId": [target.actor_id for target in targets]
            }
        }
        response = self._send_request("occupy", params)
        return response.get("data", {}).get("success", False)
 
    def select_units(self, query_params: TargetsQueryParam, is_combine: bool = False) -> None:
         """执行选择指令
         参数说明：
         - query_params: 目标查询参数（type/faction/range/restrain/actorId），最终以 {"targets": {...}} 形式发送
         - is_combine: 是否与当前选择合并；True=合并（isCombine=1），False=替换（isCombine=0）

         请求结构（示例）：
         {
           "targets": {"type": ["e1"], "faction": "己方", "range": "all"},
           "isCombine": 0
         }
         对齐接口文档 `select_unit`（参见 socket-apis.md），并与 query_actor 的类型规范化保持一致。
         """
         params_dict = query_params.to_dict()
         raw_types = params_dict.get("type", []) or []
         # 选择指令的类型字段，与查询保持同样的英文代码规范化
         if raw_types:
             params_dict["type"] = self._normalize_query_types_for_engine(raw_types)
         params = {"targets": params_dict, "isCombine": 1 if is_combine else 0}
         self._send_request("select_unit", params)

    def form_group(self, actors: List[Actor], group_id: int) -> None:
        """将单位编组"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            },
            "groupId": group_id
        }
        self._send_request("form_group", params)

    def move_camera_by_location(self, location: Location) -> None:
        """移动镜头到指定位置"""
        params = {
            "location": location.to_dict()
        }
        self._send_request("camera_move", params)

    def move_camera_by_direction(self, direction: str, distance: int) -> None:
        """按方向移动镜头"""
        params = {
            "direction": direction,
            "distance": distance
        }
        self._send_request("camera_move", params)

    def deploy_units(self, actors: List[Actor]) -> None:
        """部署单位"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            }
        }
        self._send_request("deploy", params)

    def stop(self, actors: List[Actor]) -> None:
        """停止单位"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            }
        }
        self._send_request("stop", params)

    def repair_units(self, actors: List[Actor]) -> None:
        """修理单位"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            }
        }
        self._send_request("repair", params)

    def set_rally_point(self, actors: List[Actor], location: Location) -> None:
        """设置集结点"""
        params = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            },
            "location": location.to_dict()
        }
        self._send_request("set_rally_point", params)

    # 新增：单位名称在发送给引擎前的规范化（仅针对特定单位做映射）
    def _normalize_unit_type_for_engine(self, unit_type: str) -> str:
        overrides = {
            # 建筑与单位中在引擎侧使用中文名的特例
            "dome": "雷达",   # 雷达站
            "harv": "矿车",   # 采矿车
        }
        return overrides.get(unit_type, unit_type)

    # 新增：查询时的类型规范化（将中文/别名统一为英文代码，直接发送给引擎）
    def _normalize_query_types_for_engine(self, types: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set = set()
        if not types:
            return normalized
        # 预取所有已知英文代码
        known_codes = set(self._unit_mapper.get_all_codes())
        for t in types:
            if not t:
                continue
            code = None
            # 如果本身就是已知英文代码，直接使用
            if t in known_codes:
                code = t
            else:
                # 尝试用映射将中文/别名转为英文代码
                code = self._unit_mapper.get_code(t) or t
            
            # 直接使用英文代码，API支持英文代码输入
            out = code
            
            if out not in seen:
                seen.add(out)
                normalized.append(out)
        return normalized

    def produce(self, unit_type: str, quantity: int, auto_place_building: bool = True) -> int:
        """生产单位"""
        # 仅对特定单位做规范化映射，其他保持原样
        normalized_unit_type = self._normalize_unit_type_for_engine(unit_type)
        params = {
            "units": [
                {"unit_type": normalized_unit_type, "quantity": quantity}
            ],
            "autoPlaceBuilding": auto_place_building
        }
        response = self._send_request("start_production", params)
        return response.get("data", {}).get("waitId", -1)

    def can_produce(self, unit_type: str) -> bool:
        """检查是否可以生产指定单位"""
        normalized_unit_type = self._normalize_unit_type_for_engine(unit_type)
        params = {
            "unit_type": normalized_unit_type
        }
        response = self._send_request("query_can_produce", params)
        return response.get("data", {}).get("can_produce", False)

    def query_production_queue(self, queue_type: str) -> Dict[str, Any]:
        """查询生产队列信息
        
        Args:
            queue_type: 队列类型，必须是 'Building', 'Defense', 'Infantry', 'Vehicle', 'Aircraft', 'Naval' 之一
            
        Returns:
            生产队列信息字典
        """
        valid_types = ['Building', 'Defense', 'Infantry', 'Vehicle', 'Aircraft', 'Naval']
        if queue_type not in valid_types:
            raise GameAPIError("INVALID_QUEUE_TYPE", f"队列类型必须是 {valid_types} 之一")
            
        params = {"queueType": queue_type}
        try:
            response = self._send_request("query_production_queue", params)
            return self._handle_response(response)
        except GameAPIError:
            raise
        except Exception as e:
            raise GameAPIError("QUERY_PRODUCTION_QUEUE_ERROR", f"查询生产队列失败: {str(e)}")

    def manage_production(self, queue_type: str, action: str) -> None:
        """管理生产队列"""
        params = {
            "queueType": queue_type,
            "action": action
        }
        self._send_request("manage_production", params)

    def place_building(self, queue_type: str, location: Location = None) -> None:
        """放置已生产完成的建筑
        
        Args:
            queue_type: 所属生产队列类型
            location: 建筑放置位置，如果为None则由游戏自动选择位置
        """
        params = {
            "queueType": queue_type
        }
        if location:
            params["location"] = location.to_dict()
        self._send_request("place_building", params)

    def sell_building(self, actors: List[Actor]) -> Dict[str, Any]:
        """变卖建筑
        
        Args:
            actors: 要变卖的建筑列表
            
        Returns:
            变卖结果
        """
        try:
            params = {
                "targets": {
                    "actorId": [actor.actor_id for actor in actors]
                }
            }
            response = self._send_request("sell", params)
            return {"success": True, "data": response}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wait(self, wait_id: int) -> bool:
        """等待指定的任务完成
        
        Args:
            wait_id: 等待任务的ID
            
        Returns:
            是否成功等待完成
        """
        try:
            response = self._send_request('wait', {"waitId": wait_id})
            return response.get("success", False)
        except Exception as e:
            return False
    
    def is_ready(self, wait_id: int) -> bool:
        """检查指定任务是否已完成
        
        Args:
            wait_id: 等待任务的ID
            
        Returns:
            任务是否已完成
        """
        try:
            response = self._send_request('is_ready', {"waitId": wait_id})
            return response.get("ready", False)
        except Exception as e:
            return False
    
    def produce_unit(self, unit_type: str, quantity: int, queue: str = "Infantry") -> Tuple[bool, int]:
        """生产单位的委托代理兼容接口
        
        Args:
            unit_type: 单位类型
            quantity: 生产数量
            queue: 生产队列类型（实际不使用，仅为兼容性）
            
        Returns:
            (是否成功, 等待ID)
        """
        try:
            wait_id = self.produce(unit_type, quantity, auto_place_building=True)
            success = wait_id >= 0
            return success, wait_id
        except Exception as e:
            return False, -1

    def _ensure_building_wait_buildself(self, building_code: str) -> bool:
        """已废弃：本地前置建筑检测已移除，直接依赖引擎的可生产查询"""
        return self.can_produce(building_code)
    
    def ensure_can_produce_unit(self, unit_code: str) -> bool:
        """已废弃：不再本地递归生产依赖，仅询问引擎是否可生产该单位"""
        return self.can_produce(unit_code)
    
    def move_units_by_location_and_wait(self, actors: List[Actor], location: Location, 
                                       max_wait_time: float = 10.0, tolerance_dis: int = 1) -> bool:
        """移动一批Actor到指定位置，并等待(或直到超时)
        
        Args:
            actors: 要移动的Actor列表
            location: 目标位置
            max_wait_time: 最大等待时间(秒)
            tolerance_dis: 容忍的距离误差
            
        Returns:
            是否在max_wait_time内到达
        """
        import time
        
        self.move_units_by_location(actors, location)
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            all_arrived = True
            # 更新所有单位的位置信息
            updated_actors = self.query_actor(TargetsQueryParam(
                actorId=[actor.actor_id for actor in actors]
            ))
            for actor in updated_actors:
                if actor.position is None:
                    all_arrived = False
                    break
                dx = abs(actor.position.x - location.x)
                dy = abs(actor.position.y - location.y)
                if dx > tolerance_dis or dy > tolerance_dis:
                    all_arrived = False
                    break
            if all_arrived:
                return True
            time.sleep(0.5)
        return False

    def move_units_by_path(self, actors: List[Actor], path: List[Location], attack_move: bool = False, assault_move: bool = False) -> None:
        """按路径点数组移动单位（支持闭环路径）。
        - actors: 目标单位列表
        - path: 位置对象列表（Location或{'x','y'}字典）
        - attack_move: 是否攻击移动
        - assault_move: 是否强制突击移动（可选）
        """
        if not actors or not path:
            return
        # 统一将路径转换为 dict
        normalized_path: List[Dict[str, int]] = []
        for p in path:
            if isinstance(p, Location):
                normalized_path.append(p.to_dict())
            elif isinstance(p, dict) and "x" in p and "y" in p:
                try:
                    normalized_path.append({"x": int(p["x"]), "y": int(p["y"])})
                except Exception:
                    continue
        if not normalized_path:
            return
        params: Dict[str, Any] = {
            "targets": {
                "actorId": [actor.actor_id for actor in actors]
            },
            "path": normalized_path,
            "isAttackMove": 1 if attack_move else 0
        }
        if assault_move:
            params["isAssaultMove"] = 1
        self._send_request("move_actor", params)