# -*- coding: utf-8 -*-
"""
OpenRA 助手程序 - 单位映射

这个模块负责将用户使用的单位俗称映射到游戏内部的单位名称。
"""

from typing import Dict, List, Optional


class UnitMapper:
    """单位映射器类，负责单位名称的转换"""

    def __init__(self):
        """初始化单位映射器，直接加载内置默认映射"""
        # 初始化映射字典
        self.name_to_code: Dict[str, str] = {}
        self.code_to_names: Dict[str, List[str]] = {}

        # 仅加载默认映射关系
        self._load_default_mappings()

    def _load_default_mappings(self) -> None:
        """加载默认的映射关系"""
        # 建筑 - 根据unit_list.csv更新
        # 注意：API返回的确切中文名称需要精确匹配
        self._add_mapping("fact", ["建造厂", "指挥部", "司令部", "指挥所", "基地", "建造场", "主基地", "建设工厂", "建设厂", "总部", "老家"]) 
        self._add_mapping("mcv", ["基地车", "基地建造车", "机动建设车", "基地建设车"])
        self._add_mapping("power", ["电厂", "小电厂", "发电厂", "动力站"])
        self._add_mapping("barr", ["兵营", "苏军兵营", "步兵营"])
        self._add_mapping("proc", ["矿石精炼厂", "矿场", "矿厂", "采矿场", "精炼厂"])
        self._add_mapping("weap", ["战车工厂", "载具工厂", "车厂", "重工", "重工厂", "工厂"])  
        self._add_mapping("dome", ["雷达", "雷达站", "雷达塔", "T2", "t2"])
        self._add_mapping("apwr", ["高级电厂", "大电厂", "大电", "核电", "核电厂", "核电站"])
        self._add_mapping("fix", ["维修站", "维修厂", "修理厂", "修理站"])
        self._add_mapping("afld", ["机场", "飞机场", "飞机工厂", "空军工厂", "空军基地"])
        self._add_mapping("stek", ["苏联科技中心", "科技中心", "苏联科技", "高科", "苏军高科", "高科技", "T3", "t3"])
        self._add_mapping("ftur", ["火焰塔", "喷火塔", "地堡", "火焰喷射器"])
        self._add_mapping("tsla", ["特斯拉塔", "电击塔", "电塔", "电线杆", "特斯拉电圈", "磁暴线圈"])
        self._add_mapping("sam", ["萨姆导弹", "防空导弹", "萨姆", "防空炮", "防空塔", "SAM塔", "sam塔", "AA", "aa"])

        # 步兵 - 根据unit_list.csv更新
        self._add_mapping("e1", ["步枪兵", "步兵", "杂兵", "民工", "动员兵", "好兄弟"])
        self._add_mapping("e3", ["火箭兵", "火兵", "火炮兵", "RPG", "rpg", "反坦克步兵"])

        # 车辆 - 根据unit_list.csv更新
        self._add_mapping("harv", ["采矿车", "矿车", "矿物收集车"])
        self._add_mapping("jeep", ["吉普车", "侦察车", "轻型车"])
        self._add_mapping("1tnk", ["轻型坦克", "轻坦", "小坦克"])
        self._add_mapping("2tnk", ["中型坦克", "中坦"])
        self._add_mapping("3tnk", ["重型坦克", "重坦", "苏联坦克", "坦克", "犀牛", "犀牛坦克", "主战坦克", "肥坦克"])
        self._add_mapping("4tnk", ["超重型坦克", "猛犸坦克", "猛犸", "四履带", "四履带坦克", "天启", "天启坦克", "大天启"])
        self._add_mapping("arty", ["榴弹炮", "自行火炮", "火炮"])
        self._add_mapping("v2rl", ["V2火箭发射车", "V2", "v2", "火箭车", "V3", "v3", "V3导弹", "V3火箭炮", "导弹", "火炮", "远程火炮"])
        self._add_mapping("apc", ["装甲运兵车", "APC", "apc", "运兵车"])
        self._add_mapping("ftrk", ["防空车", "防空", "反步兵车", "机枪车"])
        self._add_mapping("truk", ["卡车", "补给车"])
        self._add_mapping("mnly", ["雷管", "布雷车"])
        self._add_mapping("mgg", ["移动炮塔", "机动炮"])
        self._add_mapping("mrj", ["破坏者", "导弹快艇"])
        self._add_mapping("ttnk", ["特斯拉坦克", "电击坦克"])
        self._add_mapping("dtrk", ["爆破卡车", "自爆卡车"])
        self._add_mapping("ctnk", ["改装坦克", "火焰坦克"])

        # 飞机 - 根据unit_list.csv更新
        self._add_mapping("mig", ["米格战机", "米格", "战斗机", "轰炸机"])
        self._add_mapping("yak", ["雅克战机", "雅克", "攻击机", "反步兵飞机"])
        self._add_mapping("heli", ["武装直升机", "直升机", "阿帕奇"])
        self._add_mapping("hind", ["雌鹿直升机", "雌鹿", "攻击直升机"])
        self._add_mapping("tran", ["运输直升机", "运输机"])
        self._add_mapping("badr", ["巴德尔轰炸机", "轰炸机"])
        self._add_mapping("u2", ["侦察机", "U2侦察机", "u2侦察机"])

        print(f"已加载{len(self.code_to_names)}个默认单位映射")

    def _add_mapping(self, code: str, names: List[str]) -> None:
        """添加映射关系

        Args:
            code: 单位代码
            names: 单位名称列表
        """
        self.code_to_names[code] = names
        for name in names:
            self.name_to_code[name] = code

    def get_code(self, name: str) -> Optional[str]:
        """根据单位名称获取单位代码

        Args:
            name: 单位名称

        Returns:
            单位代码，如果找不到则返回None
        """
        code = self.name_to_code.get(name)
        
        # 如果没有找到映射，直接返回 None（不做额外回退）
        return code

    def get_names(self, code: str) -> List[str]:
        """根据单位代码获取单位名称列表

        Args:
            code: 单位代码

        Returns:
            单位名称列表，如果找不到则返回空列表
        """
        return self.code_to_names.get(code, [])

    def get_primary_name(self, code: str) -> Optional[str]:
        """根据单位代码获取主要单位名称

        Args:
            code: 单位代码

        Returns:
            主要单位名称，如果找不到则返回None
        """
        names = self.get_names(code)
        return names[0] if names else None

    def get_all_codes(self) -> List[str]:
        """获取所有单位代码

        Returns:
            所有单位代码列表
        """
        return list(self.code_to_names.keys())

    def get_all_names(self) -> List[str]:
        """获取所有单位名称

        Returns:
            所有单位名称列表
        """
        return list(self.name_to_code.keys())

    def extract_unit_types(self, text: str) -> List[str]:
        """从文本中提取单位类型（按最长匹配优先，避免子串歧义）
        
        机制说明：
        - 先将所有可能匹配的“名称-代码”按名称长度从长到短排序；
        - 扫描文本，遇到匹配则记录对应代码，并用占位符替换该片段，防止短词再次匹配到相同区域；
        - 这样可避免“防空炮”同时命中“防空（ftrk）”与“防空炮（sam）”。
        
        Args:
            text: 输入文本
            
        Returns:
            提取到的单位类型代码列表（去重、按首次命中顺序）。
        """
        unit_types: List[str] = []
        text_scan = text  # 保留原大小写以匹配中文
        
        # 构建按名称长度降序的列表（长词优先）
        name_code_items = sorted(self.name_to_code.items(), key=lambda kv: len(kv[0]), reverse=True)
        
        for name, code in name_code_items:
            if name and name in text_scan:
                # 命中则加入，并将文本中的该片段替换为同长度占位，避免子串再命中
                if code not in unit_types:
                    unit_types.append(code)
                # 防止重叠命中：将所有出现的 name 替换为占位符
                placeholder = "#" * len(name)
                text_scan = text_scan.replace(name, placeholder)
        
        return unit_types
    
    def get_mapping_text(self) -> str:
        """获取映射关系的文本表示，用于提示LLM

        Returns:
            映射关系的文本表示
        """
        lines = []
        for code, names in self.code_to_names.items():
            if names:  # 只有当有名称时才添加
                names_str = ", ".join(names)
                lines.append(f"{code}: {names_str}")
        # 确保返回字符串，避免上层拼接时报 NoneType 错误
        return "\n".join(lines)