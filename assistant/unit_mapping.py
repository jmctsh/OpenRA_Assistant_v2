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
        self._add_mapping("power", ["电厂", "小电厂", "发电厂", "动力站"]) # 小电厂的规范代码应该是powr，但引擎兼容，可以用
        self._add_mapping("barr", ["兵营", "苏军兵营", "步兵营"])
        self._add_mapping("proc", ["矿石精炼厂", "矿场", "矿厂", "采矿场", "精炼厂"])
        self._add_mapping("weap", ["战车工厂", "载具工厂", "车厂", "重工", "重工厂", "工厂"])  
        self._add_mapping("dome", ["雷达", "雷达站", "雷达塔", "T2", "t2"])
        self._add_mapping("apwr", ["高级电厂", "大电厂", "大电", "核电", "核电厂", "核电站"]) # 引擎返回值应该是核电站，但不碍事
        self._add_mapping("fix", ["维修站", "维修厂", "修理厂", "修理站"])
        self._add_mapping("afld", ["机场", "飞机场", "飞机工厂", "空军工厂", "空军基地"])
        self._add_mapping("stek", ["苏联科技中心", "科技中心", "苏联科技", "高科", "苏军高科", "高科技", "T3", "t3"])
        self._add_mapping("ftur", ["火焰塔", "喷火塔", "地堡", "火焰喷射器"])
        self._add_mapping("tsla", ["特斯拉塔", "电击塔", "电塔", "电线杆", "特斯拉电圈", "磁暴线圈"])
        self._add_mapping("sam", ["萨姆导弹", "防空导弹", "萨姆", "防空炮", "防空塔", "SAM塔", "sam塔", "AA", "aa"])
        self._add_mapping("silo", ["储存罐", "井", "存钱罐", "储油罐", "资源储存罐"])
        self._add_mapping("kenn", ["军犬窝", "狗窝", "狗屋", "狗舍", "狗棚", "军犬训练所"])
        self._add_mapping("iron", ["铁幕装置", "铁幕", "铁幕防御系统"])
        self._add_mapping("mslo", ["核弹发射井", "核弹", "导弹发射井", "核导弹井"])
        self._add_mapping("gap", ["控制点", "裂缝产生器"])
        self._add_mapping("hpad", ["直升机平台"])
        self._add_mapping("spen", ["潜艇基地"])
        self._add_mapping("syrd", ["造船厂"])
        self._add_mapping("pdox", ["超时空传送仪"])
        self._add_mapping("agun", ["盟军防空炮"])
        self._add_mapping("pbox", ["碉堡"])
        self._add_mapping("hbox", ["伪装碉堡"])
        self._add_mapping("gun", ["机枪塔"])
        self._add_mapping("atek", ["盟军科技中心"])
        self._add_mapping("oilb", ["油井", "油田", "石油井"])
        self._add_mapping("sbag", ["沙袋"])
        self._add_mapping("fenc", ["围墙"])
        self._add_mapping("brik", ["砖墙"])
        self._add_mapping("cycl", ["铁丝网"])
        self._add_mapping("barb", ["倒刺铁丝网"])
        self._add_mapping("wood", ["木墙"])

        # 步兵 - 根据unit_list.csv更新
        self._add_mapping("e1", ["步枪兵", "步兵", "杂兵", "民工", "动员兵", "好兄弟", "枪兵"])
        self._add_mapping("e3", ["火箭兵", "RPG", "rpg", "反坦克步兵"])
        self._add_mapping("e2", ["掷弹兵", "手雷兵", "手雷", "榴弹兵"])
        self._add_mapping("e4", ["喷火兵", "火焰兵", "火焰喷射兵", "火兵", "火人"])
        self._add_mapping("e6", ["工程师", "维修工程师", "技师"])
        self._add_mapping("dog", ["军犬", "狗", "小狗", "攻击犬"])
        self._add_mapping("thf", ["间谍", "特工", "潜伏者", "小偷"])
        self._add_mapping("shok", ["磁暴步兵", "电击兵", "电兵", "突击兵"])
        self._add_mapping("medi", ["医疗兵"])
        self._add_mapping("mech", ["机械师"])
        self._add_mapping("e7", ["谭雅"])
        self._add_mapping("spy", ["间谍", "盟军间谍"])

        # 车辆 - 根据unit_list.csv更新
        self._add_mapping("harv", ["采矿车", "矿车", "矿物收集车"])
        self._add_mapping("jeep", ["吉普车", "吉普", "侦查车", "军用吉普", "游骑兵", "轻型车"])
        self._add_mapping("1tnk", ["轻坦克", "轻坦", "轻型坦克", "盟军轻坦", "轻型装甲车", "小坦克"])
        self._add_mapping("2tnk", ["中型坦克", "中坦", "灰熊坦克", "灰熊"])
        self._add_mapping("3tnk", ["重型坦克", "重坦", "苏联坦克", "坦克", "犀牛", "犀牛坦克", "主战坦克", "肥坦克"])
        self._add_mapping("4tnk", ["超重型坦克", "猛犸坦克", "猛犸", "四履带", "四履带坦克", "天启", "天启坦克", "大天启"])
        self._add_mapping("arty", ["榴弹炮"])
        self._add_mapping("v2rl", ["V2火箭发射车", "V2", "v2", "火箭车", "V3", "v3", "V3导弹", "V3火箭炮", "导弹", "火炮", "远程火炮"])
        self._add_mapping("apc", ["装甲运输车", "装甲车", "运兵车"])
        self._add_mapping("ftrk", ["防空车", "防空", "反步兵车", "机枪车"])
        self._add_mapping("truk", ["运输卡车", "卡车", "补给车"])
        self._add_mapping("mnly", ["地雷部署车", "雷车", "布雷车", "雷管"])
        self._add_mapping("mgg", ["移动裂缝产生器", "移动炮塔", "机动炮"])
        self._add_mapping("mrj", ["雷达干扰车", "破坏者", "导弹快艇"])
        self._add_mapping("ttnk", ["特斯拉坦克", "磁暴坦克", "磁能坦克", "电击坦克"])
        self._add_mapping("dtrk", ["爆破卡车", "自爆卡车"])
        self._add_mapping("ctnk", ["超时空坦克", "改装坦克", "火焰坦克"])
        self._add_mapping("qtnk", ["震荡坦克", "地震坦克", "震波坦克"])
        self._add_mapping("stnk", ["相位运输车"])

        # 飞机 - 根据unit_list.csv更新
        self._add_mapping("mig", ["米格战机", "米格", "战斗机", "轰炸机"])
        self._add_mapping("yak", ["雅克战机", "雅克", "攻击机", "反步兵飞机"])
        self._add_mapping("heli", ["长弓武装直升机", "长弓", "长弓直升机", "武装直升机", "直升机", "阿帕奇"])
        self._add_mapping("hind", ["雌鹿直升机", "雌鹿攻击直升机", "雌鹿", "武装直升机", "攻击直升机"])
        self._add_mapping("tran", ["运输直升机", "运输机", "空运"])
        self._add_mapping("badr", ["巴德尔轰炸机", "轰炸机"])
        self._add_mapping("u2", ["侦察机", "U2侦察机", "u2侦察机"])
        self._add_mapping("mh60", ["黑鹰直升机", "黑鹰", "武装直升机"])

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