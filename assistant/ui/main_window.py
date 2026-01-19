# -*- coding: utf-8 -*-
"""
OpenRA 助手程序 - 主窗口

这个模块定义了助手程序的主窗口，包括命令输入区域、反馈显示区域等。
窗口设计为半透明悬浮窗口，可以显示在游戏上层。
"""

import sys
import difflib
import time
from typing import Callable, Dict, Any, Optional
import os
import asyncio
import json
import gzip
import uuid
import wave
from io import BytesIO
import struct
import threading
import re

try:
    import websockets
except ImportError:
    websockets = None

# 全局热键支持（可选）：用于在应用无焦点时捕获 Ctrl+Space 切换录音
try:
    import keyboard  # pip install keyboard
except ImportError:
    keyboard = None

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton, QLabel,
                             QComboBox, QCheckBox, QSplitter, QFrame, QTextBrowser, QApplication, QDockWidget, QTreeWidget, QTreeWidgetItem, QToolTip)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QEvent, QPoint, QSize, QTimer, QUrl
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QTextCursor, QPainter, QPen, QBrush

from typing import Optional
from ..api_client import TargetsQueryParam

try:
    from PyQt5.QtMultimedia import QAudioInput, QAudioFormat, QAudio
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False


class CommandWorker(QThread):
    """命令处理线程，用于执行命令解析和执行"""
    result_ready = pyqtSignal(dict)
    
    def __init__(self, command_parser, parent=None):
        super().__init__(parent)
        self.command_parser = command_parser
        self.command = ""
        self.running = False
        self.mode = "战略"
    
    def set_command(self, command):
        """设置要执行的命令"""
        self.command = command
    
    def set_mode(self, mode: str):
        self.mode = mode or "战略"
    
    def run(self):
        """线程主函数，执行命令解析和执行"""
        self.running = True
        
        try:
            if (self.mode or "战略") == "指令":
                result = self.command_parser.parse_command_quick(self.command)
            else:
                result = self.command_parser.parse_command(self.command)
            if self.running:  # 检查是否被取消
                self.result_ready.emit(result)
        except Exception as e:
            if self.running:
                self.result_ready.emit({
                    "original_command": self.command,
                    "parsed_command": {"command_type": "error"},
                    "result": {"success": False, "message": f"命令执行出错: {str(e)}"}
                })
        finally:
            self.running = False
    
    def stop(self):
        """停止线程"""
        self.running = False


class MainWindow(QMainWindow):
    """助手程序主窗口"""
    
    # 新增：用于跨线程安全追加反馈HTML的信号
    feedback_html_signal = pyqtSignal(str)
    asr_text_ready_signal = pyqtSignal(str)

    def __init__(self, command_parser, api_client, parent=None):
        super().__init__(parent)
        
        # 保存命令解析器和API客户端
        self.command_parser = command_parser
        self.api_client = api_client
        
        # 创建命令处理线程
        self.command_worker = CommandWorker(command_parser)
        self.command_worker.result_ready.connect(self.handle_command_result)
        
        # 连接跨线程反馈信号到UI追加方法
        self.feedback_html_signal.connect(self._append_feedback_html)
        
        # 新增：ASR 语音识别初始化
        try:
            self._init_asr_params(
                appid=os.getenv("DOUBAO_ASR_APP_ID", ""),
                token=os.getenv("DOUBAO_ASR_TOKEN", ""),
                instance=os.getenv("DOUBAO_ASR_INSTANCE", "One-sentence-recognition2000000355703689922"),
                cluster=os.getenv("DOUBAO_ASR_CLUSTER", "volcengine_input_common")
            )
        except Exception:
            pass
        # 连接 ASR 文本信号到处理方法
        try:
            self.asr_text_ready_signal.connect(self._on_asr_text_ready)
        except Exception:
            pass
        
        pass
        
        # 预设策略相关状态
        self.startup_presets_active = True
        self.preset_thread = None
        
        # 移除全局auto_loop开关，战斗默认循环，委托由UI控制
        
        # 当前正在运行的专家任务ID（区分战斗与委托）
        self.current_battle_task_id = None
        self.current_delegate_task_id = None
        # 新增：当前前置决策任务ID
        self.current_predecision_task_id = None
        # 新增：当前步兵专家任务ID
        self.current_infantry_task_id = None
        
        # 新增：专家任务状态轮询定时器
        self.expert_task_poll_timer = QTimer(self)
        self.expert_task_poll_timer.setInterval(800)
        self.expert_task_poll_timer.timeout.connect(self._poll_expert_task_status)

        # 新增：据点面板状态与定时器（3秒刷新）
        self._cp_points_cache = []
        self._cp_selected_name = None
        self._cp_poll_timer = QTimer(self)
        self._cp_poll_timer.setInterval(3000)
        self._cp_poll_timer.timeout.connect(self._poll_control_points)

        self._recruit_stats_timer = QTimer(self)
        self._recruit_stats_timer.setInterval(3000)
        self._recruit_stats_timer.timeout.connect(self._refresh_recruitment_stats)
        
        # 设置窗口属性
        self.setWindowTitle("红警AI指挥系统")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 设置窗口大小和位置
        self.resize(400, 600)
        self.move(50, 50)
        
        # 初始化UI
        self.init_ui()

        try:
            self._recruit_stats_timer.start()
        except Exception:
            pass
        
        # 安装应用级事件过滤器，确保当输入框有焦点时，能可靠捕获按键事件（支持 Ctrl+Space 切换）
        try:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
        except Exception:
            pass

        # 注册全局 Ctrl+Space 热键（切换录音）
        try:
            self._setup_global_space_hotkey()
        except Exception:
            pass

        # 窗口拖动相关变量
        self.dragging = False
        self.drag_position = QPoint()
        
        # 命令历史
        self.command_history = []
        self.history_index = -1
    
    def init_ui(self):
        """初始化用户界面"""
        # 创建中央窗口部件
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建标题栏
        title_bar = self.create_title_bar()
        main_layout.addWidget(title_bar)
        
        # 创建内容区域（左右分栏）
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setHandleWidth(6)
        self.splitter.setStyleSheet("QSplitter::handle { background: rgba(100,100,100,80); }")
        # 允许子项完全折叠（当前仅左侧主区在分栏中）
        if hasattr(self.splitter, "setChildrenCollapsible"):
            self.splitter.setChildrenCollapsible(True)

        # 左侧容器
        left_widget = QWidget(self)
        left_layout = QVBoxLayout(left_widget)
        try:
            left_widget.setStyleSheet("QScrollBar:vertical { width: 12px; margin: 0px; }")
        except Exception:
            pass
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # 选项条
        pre_opts_layout = QHBoxLayout()

        self.enable_cp_cb = QCheckBox("抢据点模式")
        self.enable_cp_cb.setChecked(False)
        self.enable_cp_cb.setStyleSheet("QCheckBox {color: white;}")
        self.enable_cp_cb.setFocusPolicy(Qt.NoFocus)
        self.enable_cp_cb.stateChanged.connect(self.on_control_point_option_changed)
        pre_opts_layout.addWidget(self.enable_cp_cb)

        self.enable_logistics_cb = QCheckBox("后勤自动循环")
        self.enable_logistics_cb.setChecked(False)
        self.enable_logistics_cb.setStyleSheet("QCheckBox {color: white;}")
        self.enable_logistics_cb.setFocusPolicy(Qt.NoFocus)
        self.enable_logistics_cb.stateChanged.connect(self.on_logistics_option_changed)
        pre_opts_layout.addWidget(self.enable_logistics_cb)

        self.enable_recruit_cb = QCheckBox("征兵自动循环")
        self.enable_recruit_cb.setChecked(False)
        self.enable_recruit_cb.setStyleSheet("QCheckBox {color: white;}")
        self.enable_recruit_cb.setFocusPolicy(Qt.NoFocus)
        self.enable_recruit_cb.stateChanged.connect(self.on_recruitment_option_changed)
        pre_opts_layout.addWidget(self.enable_recruit_cb)

        pre_opts_layout.addStretch()
        left_layout.addLayout(pre_opts_layout)

        # 第二行选项条
        second_opts_layout = QHBoxLayout()

        # 战术模块UI开关
        self.enable_tactical_ui_cb = QCheckBox("开启战术模块")
        self.enable_tactical_ui_cb.setChecked(False)
        self.enable_tactical_ui_cb.setStyleSheet("QCheckBox {color: white;}")
        self.enable_tactical_ui_cb.setFocusPolicy(Qt.NoFocus)
        self.enable_tactical_ui_cb.stateChanged.connect(self.on_tactical_module_option_changed)
        second_opts_layout.addWidget(self.enable_tactical_ui_cb)
        
        second_opts_layout.addStretch()
        left_layout.addLayout(second_opts_layout)

        self.arch_tree = QTreeWidget(self)
        self.arch_tree.setHeaderLabels(["角色", "任务"])
        self.arch_tree.setStyleSheet("QTreeWidget {background-color: rgba(45,45,45,160); color: white; border-radius: 6px; padding: 4px;} QTreeWidget::item {padding: 2px 6px;}")
        self.arch_tree.setFont(QFont("Consolas", 10))
        left_layout.addWidget(self.arch_tree)
        self.arch_timer = QTimer(self)
        self.arch_timer.setInterval(3000)
        self.arch_timer.timeout.connect(self._refresh_architecture_tree)
        self.arch_timer.start()
        try:
            self.arch_tree.itemClicked.connect(self._on_arch_item_clicked)
        except Exception:
            pass
        try:
            self._arch_tooltip_timer = QTimer(self)
            self._arch_tooltip_timer.setInterval(1000)
            self._arch_tooltip_timer.setSingleShot(True)
            self._arch_tooltip_timer.timeout.connect(self._show_arch_tooltip)
            self.arch_tree.installEventFilter(self)
        except Exception:
            pass
        
        
        
        # 防止空格触发默认按钮：明确关闭默认/自动默认
        if hasattr(self, 'send_button'):
            try:
                self.send_button.setAutoDefault(False)
                self.send_button.setDefault(False)
            except Exception:
                pass
        if hasattr(self, 'close_button'):
            try:
                self.close_button.setAutoDefault(False)
                self.close_button.setDefault(False)
            except Exception:
                pass
        
        # 初始化一次前置决策选项（应用UI默认模型至前置决策客户端）
        try:
            self.on_pre_decision_option_changed()
        except Exception:
            pass
        
        # 初始化一次委托代理开关状态
        try:
            self.on_delegate_option_changed()
        except Exception:
            pass
        
        # biods 算法增强 UI 已移除；战斗专家启动时自动启用增强，无需初始化调用
        
        # 创建反馈显示区域
        self.feedback_display = QTextBrowser()
        self.feedback_display.setReadOnly(True)
        self.feedback_display.setStyleSheet(
            "QTextBrowser {background-color: rgba(45,45,45,160); color: white; border-radius: 6px; padding: 4px;}"
        )
        self.feedback_display.setFont(QFont("Consolas", 10))
        # 允许点击链接并由我们拦截处理
        try:
            self.feedback_display.setOpenExternalLinks(False)
            # 关键修复：阻止QTextBrowser处理内部链接（否则会导航并清空当前文档）
            self.feedback_display.setOpenLinks(False)
            self.feedback_display.anchorClicked.connect(self.on_feedback_anchor_clicked)
        except Exception:
            pass
        left_layout.addWidget(self.feedback_display)
        try:
            self.arch_tree.setFrameShape(QFrame.NoFrame)
            self.feedback_display.setFrameShape(QFrame.NoFrame)
        except Exception:
            pass
        
        # 创建命令输入区域
        input_layout = QHBoxLayout()
        
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["战略", "指令"])
        self.mode_selector.setFont(QFont("Consolas", 10))
        self.mode_selector.setStyleSheet(
            "QComboBox {background-color: rgba(50,50,50,180); color: white; border-radius: 5px; padding: 4px;}"
            "QComboBox::drop-down {border: 0px;}"
            "QComboBox QAbstractItemView {background-color: rgba(40,40,40,220); color: white; selection-background-color: rgba(90,150,200,200);}"
        )
        self.mode_selector.setCurrentIndex(0)
        self.command_input = QLineEdit()
        self.command_input.setStyleSheet(
            "QLineEdit {background-color: rgba(50, 50, 50, 150); color: white; border-radius: 5px; padding: 5px;}"
        )
        self.command_input.setFont(QFont("Consolas", 10))
        self.command_input.setPlaceholderText("输入命令...")
        self.command_input.returnPressed.connect(self.send_command)
        self.command_input.installEventFilter(self)
        # 启动时将焦点放到输入框，便于快速使用 Ctrl+Space 录音
        self.command_input.setPlaceholderText("输入命令…（按 Ctrl+Space 切换录音，松开自动发送）")
        self.command_input.setFocus()
        
        self.send_button = QPushButton("发送")
        self.send_button.setStyleSheet(
            "QPushButton {background-color: rgba(70, 130, 180, 200); color: white; border-radius: 5px; padding: 5px;}"
            "QPushButton:hover {background-color: rgba(90, 150, 200, 200);}"
            "QPushButton:pressed {background-color: rgba(50, 110, 160, 200);}"
        )
        self.send_button.clicked.connect(self.send_command)
        # 明确关闭默认/自动默认，避免空格触发默认按钮
        self.send_button.setAutoDefault(False)
        self.send_button.setDefault(False)
        
        input_layout.addWidget(self.mode_selector)
        input_layout.addWidget(self.command_input)
        input_layout.addWidget(self.send_button)
        
        left_layout.addLayout(input_layout)
        
        # 右侧：据点小地图与Buff（独立模块：停靠面板，不再放入分栏）
        cp_panel = QWidget(self)
        right_layout = QVBoxLayout(cp_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        title = QLabel("据点与Buff")
        title.setStyleSheet("QLabel { color: #EEE; font-weight: 600; }")
        right_layout.addWidget(title)
        self.cp_minimap = ControlPointMiniMap(self)
        self.cp_minimap.point_clicked.connect(self._on_cp_point_clicked)
        right_layout.addWidget(self.cp_minimap)
        self.cp_buffs_label = QLabel("暂无Buff")
        self.cp_buffs_label.setStyleSheet("QLabel { color: #CCC; }")
        self.cp_buffs_label.setWordWrap(True)
        self.cp_buffs_label.setTextFormat(Qt.RichText)
        right_layout.addWidget(self.cp_buffs_label)
        right_layout.addStretch()

        # 创建 Dock 并挂载独立模块
        self.cp_dock = QDockWidget("据点与Buff", self)
        self.cp_dock.setObjectName("cpDock")
        self.cp_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        # 移除浮动/移动等按钮，仅作为固定侧边模块
        self.cp_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.cp_dock.setWidget(cp_panel)
        # 宽度锁定改为在 showEvent 中执行，避免在初始化阶段读取到不稳定的宽度
        # 初始：总是挂载到右侧 Dock 区域，并根据“抢据点”开关设置可见性
        self.addDockWidget(Qt.RightDockWidgetArea, self.cp_dock)
        if hasattr(self, 'enable_cp_cb') and not self.enable_cp_cb.isChecked():
            self.cp_dock.hide()

        self.splitter.addWidget(left_widget)
        self.splitter.setStretchFactor(0, 1)

        # 添加内容区域到主布局
        main_layout.addWidget(self.splitter)
        
        # 添加欢迎消息
        self.add_feedback("欢迎使用红警AI指挥系统！", "system")
        self.add_feedback("输入类型说明：\n- 战略：下达给秘书，由秘书传递；\n- 指令：直接执行游戏引擎相关操作；", "system")
        self.add_feedback("\n点击连队名称可直接选中下属单位。\n", "system")
        
        # 新增：显示开局预设为可点击链接
        self._render_startup_presets()

        # 初始化：根据“抢据点”开关决定是否显示独立Dock并启动轮询
        try:
            self.on_control_point_option_changed()
        except Exception:
            pass

    def _refresh_architecture_tree(self):
        try:
            ai = getattr(self.command_parser, 'ai_hq', None)
            if not ai:
                return
            try:
                recent = str(getattr(self.command_parser, '_last_strategic_input', '') or '')
            except Exception:
                recent = ""
            try:
                lr = getattr(ai, 'logistics_runner', None)
                td = getattr(lr, '_task_directive', None) if lr else None
                disp = getattr(lr, '_display_summary', None) if lr else None
                adv = getattr(lr, '_recruitment_advisory', None) if lr else None
            except Exception:
                td = None; disp = None; adv = None
            try:
                br = getattr(ai, 'brigade_runner', None)
                bt = dict(getattr(br, '_tasks', {}) or {}) if br else {}
                br_digest = {k: str((v or {}).get('mission') or '') for k, v in bt.items()}
            except Exception:
                br_digest = {}
            try:
                cs = ai.company.snapshot()
                comp_ids = set()
                for name, meta in (cs.get("companies", {}) or {}).items():
                    for uid in (meta.get("units") or []):
                        try:
                            comp_ids.add(int(uid))
                        except Exception:
                            pass
                allies_cache = getattr(ai, "_last_allies", []) or []
                all_ids = set(int(u.get("id")) for u in allies_cache if isinstance(u.get("id"), int))
                unassigned = len(all_ids - comp_ids) if all_ids else "-"
                try:
                    rr = getattr(ai, 'recruitment_runner', None)
                    rt = getattr(rr, '_task', None) if rr else None
                    recruit_task_text = (rt or {}).get('desc') or ''
                except Exception:
                    recruit_task_text = ''
                last_actions = list(getattr(ai, "_last_recruit_actions", []) or [])
                latest = last_actions[-1] if last_actions else None
            except Exception:
                unassigned = "-"; latest = None
            try:
                digest_obj = {
                    "recent": recent,
                    "logistics": {"task": td, "display": disp, "adv": adv},
                    "brigades": br_digest,
                    "recruit": {"unassigned": unassigned, "latest": latest, "task": recruit_task_text}
                }
                digest = json.dumps(digest_obj, ensure_ascii=False, sort_keys=True)
                last = getattr(self, '_arch_last_digest', None)
                if last == digest:
                    return
                setattr(self, '_arch_last_digest', digest)
            except Exception:
                pass
            expanded_paths = set()
            try:
                def _collect(node, prefix):
                    try:
                        if node.isExpanded():
                            expanded_paths.add(prefix)
                        for j in range(node.childCount()):
                            ch = node.child(j)
                            if ch:
                                _collect(ch, prefix + "/" + ch.text(0))
                    except Exception:
                        pass
                count = self.arch_tree.topLevelItemCount()
                for i in range(count):
                    item = self.arch_tree.topLevelItem(i)
                    if item:
                        _collect(item, item.text(0))
            except Exception:
                expanded_paths = set()
            self.arch_tree.clear()
            root_cmd = QTreeWidgetItem(["司令", ""])
            self.arch_tree.addTopLevelItem(root_cmd)
            try:
                recent = str(getattr(self.command_parser, '_last_strategic_input', '') or '')
            except Exception:
                recent = ""
            sec_item = QTreeWidgetItem(["秘书", recent])
            try:
                sec_item.setToolTip(1, recent)
            except Exception:
                pass
            try:
                routes = getattr(self.command_parser, '_secretary_routes', []) or []
                # 不显示JSON，仅显示最近一次战略文本
            except Exception:
                pass
            self.arch_tree.addTopLevelItem(sec_item)

            logi = QTreeWidgetItem(["后勤部长", "无"])
            try:
                lr = getattr(ai, 'logistics_runner', None)
                adv = getattr(lr, '_recruitment_advisory', None)
                lt = str(getattr(self.command_parser, '_logistics_task_text', '') or '')
                def _short_task(d):
                    if isinstance(d, dict):
                        return str(d.get('task') or d.get('name') or d.get('hint') or '有任务')
                    return str(d) if d else "无"
                left = lt if lt else "自主决策中"
                atext = f"征兵留言:{_short_task((adv or {}).get('notes') or (adv or {}).get('priority_units'))}" if adv else "征兵留言:无"
                logi.setText(1, f"{left} | {atext}")
            except Exception:
                pass
            try:
                logi.setToolTip(1, logi.text(1))
            except Exception:
                pass
            self.arch_tree.addTopLevelItem(logi)

            brig_root = QTreeWidgetItem(["旅长", ""])
            self.arch_tree.addTopLevelItem(brig_root)
            try:
                for b in getattr(ai, 'brigades', []) or []:
                    bname = getattr(b, 'name', '')
                    bitem = QTreeWidgetItem([bname, ""])
                    try:
                        br = getattr(ai, 'brigade_runner', None)
                        bt = getattr(br, '_tasks', {})
                        comps_map = getattr(b, 'companies', {}) or {}
                        activated = False
                        for cname, comp in comps_map.items():
                            try:
                                ids = list(getattr(comp, 'unit_ids', []) or [])
                                if ids:
                                    activated = True
                                    break
                            except Exception:
                                pass
                        if bt.get(bname):
                            task_meta = (bt.get(bname) or {})
                            mission = str(task_meta.get('mission') or '')
                            mission_raw = str(task_meta.get('mission_raw') or mission)
                            source = str(task_meta.get('source') or '')
                            label = mission_raw
                            bitem.setText(1, f"秘书:{label}" if source == 'secretary' else label)
                        else:
                            bitem.setText(1, "自主决策中" if activated else "休眠中")
                        try:
                            bitem.setToolTip(1, bitem.text(1))
                        except Exception:
                            pass
                    except Exception:
                        pass
                    comps = getattr(b, 'companies', {}) or {}
                    for cname, comp in comps.items():
                        status_text = ""
                        try:
                            ids = list(getattr(comp, 'unit_ids', []) or [])
                            if ids:
                                status_text = "待命"
                                car = getattr(ai, 'company_attack_runner', None)
                                ct = getattr(car, '_tasks', {})
                                if ct.get(cname):
                                    status_text = "作战"
                            else:
                                status_text = "无"
                        except Exception:
                            status_text = "无"
                        citem = QTreeWidgetItem([cname, status_text])
                        bitem.addChild(citem)
                    brig_root.addChild(bitem)
            except Exception:
                pass

            recr = QTreeWidgetItem(["征兵部长", ""]) 
            try:
                cs = ai.company.snapshot()
                comp_ids = set()
                for name, meta in (cs.get("companies", {}) or {}).items():
                    for uid in (meta.get("units") or []):
                        try:
                            comp_ids.add(int(uid))
                        except Exception:
                            pass
                allies_cache = getattr(ai, "_last_allies", []) or []
                all_ids = set(int(u.get("id")) for u in allies_cache if isinstance(u.get("id"), int))
                unassigned = len(all_ids - comp_ids) if all_ids else "-"
                recr.setText(1, f"未编入:{unassigned}")
                recr.setToolTip(1, recr.text(1))
            except Exception:
                pass
            self.arch_tree.addTopLevelItem(recr)
            try:
                def _restore(node, prefix):
                    try:
                        if prefix in expanded_paths:
                            node.setExpanded(True)
                        for j in range(node.childCount()):
                            ch = node.child(j)
                            if ch:
                                _restore(ch, prefix + "/" + ch.text(0))
                    except Exception:
                        pass
                for i in range(self.arch_tree.topLevelItemCount()):
                    it = self.arch_tree.topLevelItem(i)
                    if it:
                        _restore(it, it.text(0))
            except Exception:
                # 兜底：全部展开
                try:
                    self.arch_tree.expandAll()
                except Exception:
                    pass
            pass
            try:
                display = str(getattr(self.command_parser, '_secretary_report', '') or '')
                if not display:
                    display = recent
                if display:
                    digest = f"秘书：{display}"
                    last_digest = getattr(self, '_last_task_digest', None)
                    if digest != last_digest:
                        setattr(self, '_last_task_digest', digest)
                        try:
                            self.add_feedback(digest, "normal")
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    def _on_arch_item_clicked(self, item, column):
        try:
            name = item.text(0)
            ai = getattr(self.command_parser, 'ai_hq', None)
            if not ai:
                return
            cs = ai.company.snapshot()
            comps = (cs.get("companies") or {})
            meta = comps.get(name)
            if not meta:
                return
            unit_ids = list(meta.get("units") or [])
            if not unit_ids:
                return
            try:
                self.api_client.select_units(TargetsQueryParam(actorId=[int(uid) for uid in unit_ids], range="all"), is_combine=False)
            except Exception as e:
                pass
        except Exception:
            pass
    
    # 新增：据点小地图与Buff折叠开关逻辑（使用独立 Dock 面板）
    def showEvent(self, event):
        super().showEvent(event)
        # 在窗口显示后锁定主界面（centralWidget）当前宽度，避免初始化阶段读取到不稳定宽度
        if not hasattr(self, '_fixed_width_locked') or not self._fixed_width_locked:
            cw = self.centralWidget()
            if cw is not None:
                w = cw.width()
                if isinstance(w, int) and w > 0:
                    cw.setFixedWidth(w)
                    self._fixed_width_locked = True

    def on_control_point_option_changed(self, state: Optional[int] = None):
        try:
            enabled = bool(self.enable_cp_cb.isChecked()) if hasattr(self, 'enable_cp_cb') else False
        except Exception:
            enabled = False
        try:
            if hasattr(self, 'cp_dock') and self.cp_dock:
                if enabled:
                    self.cp_dock.show()
                else:
                    self.cp_dock.hide()
        except Exception:
            pass
        try:
            if hasattr(self, '_cp_poll_timer'):
                if enabled and not self._cp_poll_timer.isActive():
                    self._cp_poll_timer.start()
                if (not enabled) and self._cp_poll_timer.isActive():
                    self._cp_poll_timer.stop()
        except Exception:
            pass
        if enabled:
            try:
                self._poll_control_points()
            except Exception:
                pass
        else:
            try:
                if hasattr(self, 'cp_minimap') and self.cp_minimap:
                    self.cp_minimap.set_points([])
                    self.cp_minimap.set_selected_name(None)
            except Exception:
                pass
            try:
                if hasattr(self, 'cp_buffs_label') and self.cp_buffs_label:
                    self.cp_buffs_label.setText("暂无Buff")
            except Exception:
                pass
    
    def on_delegate_option_changed(self):
        """委托代理开关变更：勾选=启动委托任务(自动循环)，取消=终止委托任务"""
        try:
            enabled = bool(self.enable_delegate_cb.isChecked()) if hasattr(self, 'enable_delegate_cb') else False
            if not hasattr(self, 'expert_task_manager') or not self.expert_task_manager:
                return
            
            if enabled:
                # 若已在运行则不重复提交
                if getattr(self, 'current_delegate_task_id', None):
                    return
                # 首次启用委托代理也视为输入了指令：锁定开局预设
                if getattr(self, 'startup_presets_active', False):
                    self._lock_startup_presets()
                # 提交委托任务，开启自动循环
                self.current_delegate_task_id = self.expert_task_manager.submit_delegate_task(conversation_context="", auto_loop=True)
                if hasattr(self, 'expert_task_poll_timer'):
                    self.expert_task_poll_timer.start()
            else:
                # 关闭则取消任务
                if getattr(self, 'current_delegate_task_id', None):
                    self.expert_task_manager.cancel_task(self.current_delegate_task_id)
        except Exception:
            pass

    def on_logistics_option_changed(self, state: Optional[int] = None):
        try:
            enabled = bool(self.enable_logistics_cb.isChecked()) if hasattr(self, 'enable_logistics_cb') else False
        except Exception:
            enabled = False
        try:
            ai = getattr(self.command_parser, 'ai_hq', None)
            if not ai:
                return
            try:
                setattr(ai, '_auto_logistics_enabled', enabled)
            except Exception:
                pass
            try:
                if enabled:
                    setattr(ai, '_has_started', True)
                    if hasattr(ai, 'staff') and ai.staff:
                        ai.staff.mark_started()
                
            except Exception:
                pass
            if enabled:
                if hasattr(ai, 'logistics_runner'):
                    ai.logistics_runner.start()
            else:
                if hasattr(ai, 'logistics_runner'):
                    ai.logistics_runner.stop()
        except Exception:
            pass

    def on_recruitment_option_changed(self, state: Optional[int] = None):
        try:
            enabled = bool(self.enable_recruit_cb.isChecked()) if hasattr(self, 'enable_recruit_cb') else False
        except Exception:
            enabled = False
        try:
            ai = getattr(self.command_parser, 'ai_hq', None)
            if not ai:
                return
            try:
                setattr(ai, '_auto_recruit_enabled', enabled)
            except Exception:
                pass
            try:
                if enabled:
                    setattr(ai, '_has_started', True)
                    if hasattr(ai, 'staff') and ai.staff:
                        ai.staff.mark_started()
            except Exception:
                pass
            if enabled:
                if hasattr(ai, 'recruitment_runner'):
                    ai.recruitment_runner.start()
            else:
                if hasattr(ai, 'recruitment_runner'):
                    ai.recruitment_runner.stop()
        except Exception:
            pass

    def on_battle_option_changed(self):
        """战斗专家开关变更：勾选=启动战斗专家(自动循环)，取消=终止战斗专家
        同时根据 biods 标志启动/停止 biods 后台循环，仅在战斗专家运行期间生效。"""
        try:
            enabled = bool(self.enable_battle_cb.isChecked()) if hasattr(self, 'enable_battle_cb') else False
            if not hasattr(self, 'expert_task_manager') or not self.expert_task_manager:
                return
            current_id = getattr(self, 'current_battle_task_id', None)
            if enabled:
                if current_id:
                    # 若已在运行则不重复提交
                    try:
                        task = self.expert_task_manager.get_task_status(current_id)
                        status_name = getattr(task.status, 'value', None) if task else None
                        if task and status_name == "running":
                            # 运行中，避免重复提交任务
                            return
                    except Exception:
                        pass
                    # 若任务已结束，清空id以便重新提交
                    self.current_battle_task_id = None
                # 旧战斗专家任务已移除
                self.current_battle_task_id = None
                # 自动启用 biods 增强（不再需要 UI 开关）
                # 战术模块已常驻，此处仅需确保注入 LLM
                try:
                    unit_mapper = getattr(self.command_parser, 'unit_mapper', None)
                    llm_proc = getattr(self.command_parser, 'llm_attack_processor', None)
                    if unit_mapper is not None:
                        self._ensure_biods_initialized()
                        if self.biods_enhancer:
                            self.biods_enhancer.enabled = True
                            if llm_proc and hasattr(llm_proc, 'set_biods_enhancer'):
                                llm_proc.set_biods_enhancer(self.biods_enhancer)
                except Exception:
                    pass
                if hasattr(self, 'expert_task_poll_timer'):
                    self.expert_task_poll_timer.start()
            else:
                if current_id:
                    self.expert_task_manager.cancel_task(current_id)
                # 停止 biods 后台
                try:
                    if hasattr(self, 'biods_enhancer') and self.biods_enhancer is not None and hasattr(self.biods_enhancer, 'stop'):
                        self.biods_enhancer.stop()
                except Exception:
                    pass
                # biods 算法增强 UI 已移除，无需恢复开关
        except Exception:
            pass

    def on_tactical_module_option_changed(self):
        """战术模块开关变更：勾选=启动+显示UI，取消=停止+隐藏UI"""
        try:
            enabled = bool(self.enable_tactical_ui_cb.isChecked())
            
            # 确保战术模块已初始化
            self._ensure_biods_initialized()
            
            if self.biods_enhancer:
                if enabled:
                    # 启动并显示UI
                    if hasattr(self.biods_enhancer, 'start'):
                        self.biods_enhancer.start(self.api_client, show_log_window=True)
                        # 确保窗口显示（start若已运行可能不会重新弹窗）
                        if hasattr(self.biods_enhancer, 'show_log_window'):
                            self.biods_enhancer.show_log_window()
                else:
                    # 停止并隐藏UI
                    if hasattr(self.biods_enhancer, 'stop'):
                        self.biods_enhancer.stop()
                    if hasattr(self.biods_enhancer, 'hide_log_window'):
                        self.biods_enhancer.hide_log_window()
        except Exception:
            pass

    def _ensure_biods_initialized(self):
        """确保战术模块已加载并启动（随主程序常驻）"""
        try:
            unit_mapper = getattr(self.command_parser, 'unit_mapper', None)
            llm_proc = getattr(self.command_parser, 'llm_attack_processor', None)
            
            if unit_mapper is not None:
                if not hasattr(self, 'biods_enhancer') or self.biods_enhancer is None:
                    try:
                        import importlib
                        enhancer_module = importlib.import_module("assistant.tactical_core.enhancer")
                        BiodsEnhancer = enhancer_module.BiodsEnhancer
                        self.biods_enhancer = BiodsEnhancer(enabled=True)
                        
                        # 注入到 LLM 处理器
                        if llm_proc and hasattr(llm_proc, 'set_biods_enhancer'):
                            llm_proc.set_biods_enhancer(self.biods_enhancer)
                            
                        # 立即启动后台线程（不显示窗口）
                        if hasattr(self.biods_enhancer, 'start'):
                            self.biods_enhancer.start(self.api_client, show_log_window=False)
                            # 强制开启日志记录，只控制窗口显隐
                            import os
                            os.environ["LLM_DEBUG"] = "1"
                            
                    except ImportError:
                        print("Warning: Failed to import BiodsEnhancer from assistant.tactical_core")
                        self.biods_enhancer = None
        except Exception:
            pass

    def on_infantry_option_changed(self):
        """步兵战斗专家开关变更：勾选=启动步兵专家(自动循环)，取消=终止步兵专家。
        注意：与原战斗专家不冲突，可同时运行。"""
        try:
            enabled = bool(self.enable_infantry_cb.isChecked()) if hasattr(self, 'enable_infantry_cb') else False
            if not hasattr(self, 'expert_task_manager') or not self.expert_task_manager:
                return
            current_id = getattr(self, 'current_infantry_task_id', None)
            if enabled:
                if current_id:
                    # 已在运行则不重复提交
                    try:
                        task = self.expert_task_manager.get_task_status(current_id)
                        status_name = getattr(task.status, 'value', None) if task else None
                        if task and status_name == "running":
                            return
                    except Exception:
                        pass
                    # 若任务已结束，清空id以便重新提交
                    self.current_infantry_task_id = None
                # 提交步兵专家任务，默认自动循环
                self.current_infantry_task_id = self.expert_task_manager.submit_infantry_task(auto_loop=True)
                if hasattr(self, 'expert_task_poll_timer'):
                    self.expert_task_poll_timer.start()
            else:
                if current_id:
                    self.expert_task_manager.cancel_task(current_id)
        except Exception:
            pass
            if enabled:
                if current_id:
                    # 若已在运行则不重复提交
                    try:
                        task = self.expert_task_manager.get_task_status(current_id)
                        status_name = getattr(task.status, 'value', None) if task else None
                        if task and status_name == "running":
                            # 运行中，避免重复提交任务
                            return
                    except Exception:
                        pass
                    # 若任务已结束，清空id以便重新提交
                    self.current_battle_task_id = None
                # 旧战斗专家任务已移除
                self.current_battle_task_id = None
                # 自动启用 biods 增强（不再需要 UI 开关）
                # 战术模块已常驻，此处仅需确保注入 LLM
                try:
                    unit_mapper = getattr(self.command_parser, 'unit_mapper', None)
                    llm_proc = getattr(self.command_parser, 'llm_attack_processor', None)
                    if unit_mapper is not None:
                        self._ensure_biods_initialized()
                        if self.biods_enhancer:
                            self.biods_enhancer.enabled = True
                            if llm_proc and hasattr(llm_proc, 'set_biods_enhancer'):
                                llm_proc.set_biods_enhancer(self.biods_enhancer)
                except Exception:
                    pass
                if hasattr(self, 'expert_task_poll_timer'):
                    self.expert_task_poll_timer.start()
            else:
                if current_id:
                    self.expert_task_manager.cancel_task(current_id)
                # 停止 biods 后台
                try:
                    if hasattr(self, 'biods_enhancer') and self.biods_enhancer is not None and hasattr(self.biods_enhancer, 'stop'):
                        self.biods_enhancer.stop()
                except Exception:
                    pass
                # biods 算法增强 UI 已移除，无需恢复开关
        except Exception:
            pass

    def send_command(self):
        """发送命令"""
        command = self.command_input.text().strip()
        if not command:
            return
        
        # 首次输入指令后锁定开局预设（置灰并禁止点击）
        if getattr(self, 'startup_presets_active', False):
            self._lock_startup_presets()
        
        # 添加命令到历史记录
        self.command_history.append(command)
        self.history_index = len(self.command_history)
        
        # 显示命令
        self.add_feedback(f">> {command}", "command")
        
        # 清空输入框
        self.command_input.clear()
        
        # 发送期间禁用输入与按钮，避免重复发送
        try:
            if hasattr(self, 'command_input'):
                self.command_input.setEnabled(False)
            if hasattr(self, 'send_button'):
                self.send_button.setEnabled(False)
        except Exception:
            pass
        
        pass
        
        # 如果有正在执行的命令，停止它
        if self.command_worker.isRunning():
            self.command_worker.stop()
            self.command_worker.wait()
        
        # 设置新命令并启动线程
        try:
            self.command_worker.set_mode(self.mode_selector.currentText())
        except Exception:
            pass
        self.command_worker.set_command(command)
        self.command_worker.start()
    
    def handle_command_result(self, result):
        """处理命令执行结果
        
        Args:
            result: 命令执行结果字典
        """
        # 结果返回后恢复输入与按钮
        try:
            if hasattr(self, 'command_input'):
                self.command_input.setEnabled(True)
                self.command_input.setFocus()
            if hasattr(self, 'send_button'):
                self.send_button.setEnabled(True)
        except Exception:
            pass
        
        # 提取结果信息
        success = result.get("result", {}).get("success", False)
        message = result.get("result", {}).get("message", "")
        parsed = result.get("parsed_command", {}) or {}
        
        pass
        
        # 显示结果（概览信息）
        message_type = "success" if success else "error"
        try:
            cmd_type = str(parsed.get("command_type") or "")
            if cmd_type != "strategic" and message:
                self.add_feedback(message, message_type)
        except Exception:
            if message:
                self.add_feedback(message, message_type)
        
        # 如果标准化后的指令与原始输入不同，显示标准化指令（可选差异高亮）
        orig_cmd = result.get("original_command")
        norm_cmd = result.get("normalized_command")
        if isinstance(norm_cmd, str) and norm_cmd and norm_cmd != orig_cmd:
            std_html = self._build_standardization_html(orig_cmd or "", norm_cmd)
            # 先显示结果message，再单独换行展示标准化HTML，避免与其它提示粘连
            self.add_feedback(std_html, "normal")
        
        # 判断是否为概览类查询（优先依据解析信息；兜底根据数据结构判断）
        result_payload = result.get("result", {})
        data = result_payload.get("data") if isinstance(result_payload, dict) else None
        is_overview = (
            parsed.get("command_type") == "query" and parsed.get("query_type") in {"unified_overview", "buildings_overview", "units_overview"}
        ) or (
            isinstance(data, dict) and ("actor_stats" in data or "actors" in data or "building_stats" in data or "unit_stats" in data)
        )
        
        # 对建筑位置查询同样不展示原始明细数据（仅展示汇总 message）
        query_type = parsed.get("query_type")
        suppress_raw = is_overview or (query_type == "building_position") or (str(parsed.get("command_type") or "") == "strategic")
        
        # 仅对非概览类且不需要抑制原始数据的查询显示详细数据
        if not suppress_raw:
            if isinstance(data, dict):
                for key, value in data.items():
                    if str(key) in {"routes_executed"}:
                        continue
                    self.add_feedback(f"{key}: {value}", "normal")
            elif data is not None:
                self.add_feedback(f"数据: {data}", "normal")
    
    def cancel_current_expert_task(self):
        """取消当前运行中的专家任务（战斗与委托）"""
        try:
            any_cancelled = False
            if hasattr(self, 'expert_task_manager') and self.expert_task_manager:
                if getattr(self, 'current_battle_task_id', None):
                    if self.expert_task_manager.cancel_task(self.current_battle_task_id):
                        any_cancelled = True
                if getattr(self, 'current_delegate_task_id', None):
                    if self.expert_task_manager.cancel_task(self.current_delegate_task_id):
                        any_cancelled = True
            if any_cancelled:
                self.add_feedback("已请求取消运行中的专家任务，正在停止…", "system")
            else:
                self.add_feedback("未找到正在运行的专家任务", "error")
        except Exception:
            pass

    def create_title_bar(self):
        """创建自定义标题栏"""
        title_bar = QFrame(self)
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet(
            "QFrame {background-color: rgba(20, 20, 20, 180); border-top-left-radius: 10px; border-top-right-radius: 10px; border: 1px solid rgba(100, 100, 100, 150);}"
        )
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(8, 0, 8, 0)
        
        title_label = QLabel("红警AI指挥系统")
        title_label.setStyleSheet("QLabel {color: white;}")
        title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        layout.addWidget(title_label)
        layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton {background-color: transparent; color: #CCCCCC; border: none;}"
            "QPushButton:hover {color: white;}"
        )
        # 避免空格键激活关闭按钮导致误触退出
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        return title_bar

    def _init_asr_params(self, appid: str, token: str, instance: str, cluster: str):
        # 保存参数
        self._asr_appid = appid or ""
        self._asr_token = token or ""
        self._asr_instance = instance or "One-sentence-recognition2000000355703689922"
        self._asr_cluster = cluster or "volcengine_input_common"
        # Hotword table id (boosting) strictly from env; no hardcoded default
        self._asr_boosting_table_id = os.getenv("DOUBAO_ASR_HOTWORD_ID") or ""
        # WebSocket URL
        self._asr_ws_url = "wss://openspeech.bytedance.com/api/v2/asr"
        # 录音状态
        self._recording = False
        self._audio_input = None
        self._audio_io_device = None
        self._audio_buffer = bytearray()
        # 准备音频格式：16kHz 单声道 16-bit PCM
        self._audio_format = None
        if AUDIO_AVAILABLE:
            fmt = QAudioFormat()
            fmt.setSampleRate(16000)
            fmt.setChannelCount(1)
            fmt.setSampleSize(16)
            fmt.setCodec("audio/pcm")
            fmt.setByteOrder(QAudioFormat.LittleEndian)
            fmt.setSampleType(QAudioFormat.SignedInt)
            self._audio_format = fmt
        else:
            self.add_feedback("未检测到 PyQt5.QtMultimedia，语音输入不可用。", "error")

    def _start_recording(self):
        if not AUDIO_AVAILABLE:
            self.add_feedback("当前环境不支持音频录制。", "error")
            return
        if self._recording:
            return
        if not self._asr_appid or not self._asr_token:
            self.add_feedback("未配置 ASR 凭据（DOUBAO_ASR_APP_ID/DOUBAO_ASR_TOKEN）。", "error")
            return
        try:
            self._audio_buffer = bytearray()
            self._audio_input = QAudioInput(self._audio_format, self)
            self._audio_io_device = self._audio_input.start()
            try:
                # 持续读取数据以避免内部缓冲区溢出
                self._audio_io_device.readyRead.connect(self._on_audio_ready_read)
            except Exception:
                pass
            self._recording = True
            # 录音开始提示：为避免与上一条消息粘连，这里显式加入前导换行
            self.add_feedback("<br/>开始录音…（再次按 Ctrl+Space 结束并发送）", "system")
        except Exception as e:
            self.add_feedback(f"启动录音失败：{e}", "error")
            self._recording = False
            self._audio_input = None
            self._audio_io_device = None

    def _on_audio_ready_read(self):
        try:
            if self._audio_input and self._audio_io_device:
                avail = self._audio_input.bytesReady()
                if avail > 0:
                    data = self._audio_io_device.read(avail)
                    try:
                        data = bytes(data)
                    except Exception:
                        data = b""
                    if data:
                        self._audio_buffer.extend(data)
        except Exception:
            pass

    def _pull_audio_chunk(self) -> bytes:
        if not self._audio_io_device:
            return b""
        try:
            # 尝试一次性读取可用数据
            bytes_available = self._audio_input.bytesReady() if self._audio_input else 0
            if bytes_available > 0:
                data = self._audio_io_device.read(bytes_available)
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
                # 某些平台返回 QByteArray
                try:
                    return bytes(data)
                except Exception:
                    return b""
            return b""
        except Exception:
            return b""

    def _stop_recording_and_transcribe(self):
        if not self._recording:
            return
        try:
            # 拉取残留数据
            chunk = self._pull_audio_chunk()
            if chunk:
                self._audio_buffer.extend(chunk)
            # 停止
            if self._audio_input:
                self._audio_input.stop()
            self._recording = False
            self.add_feedback("结束录音，开始识别…", "system")
            # 将 PCM 封装为 WAV (16kHz, 16-bit, mono)
            pcm_bytes = bytes(self._audio_buffer)
            wav_bytes = self._pcm_to_wav(pcm_bytes, channels=1, sample_width=2, sample_rate=16000)
            # 调起后台识别
            self._run_asr_in_background(wav_bytes, sample_rate=16000)
        except Exception as e:
            self.add_feedback(f"停止录音失败：{e}", "error")
        finally:
            self._audio_input = None
            self._audio_io_device = None
            self._audio_buffer = bytearray()

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, channels: int, sample_width: int, sample_rate: int) -> bytes:
        with BytesIO() as buffer:
            wf = wave.open(buffer, 'wb')
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
            wf.close()
            return buffer.getvalue()

    def _run_asr_in_background(self, wav_bytes: bytes, sample_rate: int = 16000):
        """启动异步ASR识别工作线程，并将结果通过信号回传UI。"""
        try:
            if websockets is None:
                self.add_feedback("未安装 websockets 库，无法进行语音识别。请先安装依赖：pip install websockets", "error")
                return
        except Exception:
            pass
        # 凭据检查
        if not getattr(self, '_asr_appid', None) or not getattr(self, '_asr_token', None):
            self.add_feedback("未配置 ASR 凭据（DOUBAO_ASR_APP_ID/DOUBAO_ASR_TOKEN）。", "error")
            return
        # 启动工作线程
        worker = _AsrWorker(
            wav_bytes=wav_bytes,
            sample_rate=sample_rate,
            appid=self._asr_appid,
            token=self._asr_token,
            cluster=getattr(self, '_asr_cluster', None),
            ws_url=getattr(self, '_asr_ws_url', None),
            boosting_table_id=getattr(self, '_asr_boosting_table_id', None),
        )
        self._asr_worker = worker
        worker.text_ready.connect(self.asr_text_ready_signal.emit)
        worker.error_msg.connect(lambda msg: self.add_feedback(msg, "error"))
        worker.finished.connect(lambda: setattr(self, "_asr_worker", None))
        worker.start()

    def _on_asr_text_ready(self, text: str):
        text = (text or "").strip()
        if not text:
            try:
                self.add_feedback("识别结果为空。", "error")
            except Exception:
                pass
            return
        # 自动填充并发送，不需要确认
        try:
            self.command_input.setText(text)
            self.send_command()
        except Exception:
            # 兜底：仅展示识别结果
            try:
                self.add_feedback(f"语音识别：{self._escape_html(text)}", "system")
            except Exception:
                pass

    def _toggle_recording(self):
        """切换录音状态：正在录音则结束并转写，否则开始录音。"""
        try:
            if getattr(self, '_recording', False):
                QTimer.singleShot(0, self._stop_recording_and_transcribe)
            else:
                QTimer.singleShot(0, self._start_recording)
        except Exception:
            pass

    def _setup_global_space_hotkey(self):
        """通过 keyboard 注册全局 Ctrl+Space 切换录音（不拦截系统/游戏按键）。"""
        # 若之前存在旧的空格钩子，先卸载
        try:
            if getattr(self, '_keyboard_hook', None) is not None and keyboard is not None:
                try:
                    keyboard.unhook(self._keyboard_hook)
                except Exception:
                    pass
                self._keyboard_hook = None
        except Exception:
            pass

        if keyboard is None:
            try:
                self.add_feedback("未安装 keyboard 库，无法在应用外捕获 Ctrl+Space。请安装：pip install keyboard。", "system")
            except Exception:
                pass
            return

        # 避免重复注册
        if getattr(self, '_keyboard_hotkey', None) is not None:
            return
        try:
            # 注册全局 Ctrl+Space 为切换录音
            self._keyboard_hotkey = keyboard.add_hotkey(
                'ctrl+space',
                lambda: QTimer.singleShot(0, self._toggle_recording),
                suppress=False,
                trigger_on_release=False
            )
        except Exception:
            try:
                self.add_feedback("注册 Ctrl+Space 全局热键失败。", "error")
            except Exception:
                pass
            self._keyboard_hotkey = None

    def eventFilter(self, obj, event):
        # 仅处理 Ctrl+Space 切换录音；不再拦截普通空格
        try:
            if obj is getattr(self, 'arch_tree', None):
                if event.type() == QEvent.MouseMove:
                    idx = self.arch_tree.indexAt(event.pos())
                    if idx.isValid() and idx.column() == 1:
                        item = self.arch_tree.itemAt(event.pos())
                        if item:
                            try:
                                text = item.toolTip(1) or item.text(1)
                            except Exception:
                                text = item.text(1)
                            try:
                                role_ok = str(item.text(0)) in {"秘书", "征兵部长", "后勤部长"}
                            except Exception:
                                role_ok = False
                            if not role_ok:
                                try:
                                    if hasattr(self, '_arch_tooltip_timer') and self._arch_tooltip_timer:
                                        self._arch_tooltip_timer.stop()
                                    QToolTip.hideText()
                                    setattr(self, '_arch_hover_index', None)
                                except Exception:
                                    pass
                                return True
                            # 若移到新行，重置计时并隐藏现有提示
                            try:
                                last_idx = getattr(self, '_arch_hover_index', None)
                            except Exception:
                                last_idx = None
                            if (last_idx is None) or (last_idx != idx):
                                try:
                                    QToolTip.hideText()
                                except Exception:
                                    pass
                                setattr(self, '_arch_hover_index', idx)
                                self._arch_tooltip_text = text
                                self._arch_tooltip_pos = self.arch_tree.mapToGlobal(event.pos())
                                if hasattr(self, '_arch_tooltip_timer') and self._arch_tooltip_timer:
                                    self._arch_tooltip_timer.stop()
                                    self._arch_tooltip_timer.start()
                            else:
                                # 同一行移动：仅更新位置，不重启计时
                                self._arch_tooltip_pos = self.arch_tree.mapToGlobal(event.pos())
                    else:
                        # 非任务列或无效索引：停止计时并隐藏
                        try:
                            if hasattr(self, '_arch_tooltip_timer') and self._arch_tooltip_timer:
                                self._arch_tooltip_timer.stop()
                            QToolTip.hideText()
                            setattr(self, '_arch_hover_index', None)
                        except Exception:
                            pass
                if event.type() == QEvent.Leave:
                    try:
                        if hasattr(self, '_arch_tooltip_timer') and self._arch_tooltip_timer:
                            self._arch_tooltip_timer.stop()
                        QToolTip.hideText()
                        setattr(self, '_arch_hover_index', None)
                    except Exception:
                        pass
                if event.type() == QEvent.ToolTip:
                    # 抑制默认提示行为，统一由定时器控制显示
                    event.accept()
                    return True
            if event.type() == QEvent.ShortcutOverride:
                if (event.key() == Qt.Key_Space) and (event.modifiers() & Qt.ControlModifier):
                    # 若已注册全局热键，则避免在 Qt 里再次触发，直接吸收事件防止插入字符
                    if getattr(self, '_keyboard_hotkey', None) is not None:
                        event.accept()
                        return True
                    event.accept()
                    return True
            if event.type() == QEvent.KeyPress:
                if (event.key() == Qt.Key_Space) and (event.modifiers() & Qt.ControlModifier):
                    # 若已注册全局热键，则避免在 Qt 内再次调用切换逻辑（防止双触发导致立刻停止）
                    if getattr(self, '_keyboard_hotkey', None) is not None:
                        event.accept()
                        return True
                    if not event.isAutoRepeat():
                        self._toggle_recording()
                    event.accept()
                    return True
        except Exception:
            # 防御性：任何异常都不应中断事件分发
            pass

        # 仅当命令输入框有焦点时，处理历史上下键
        target_is_input = (obj is getattr(self, 'command_input', None)) or (
            hasattr(self, 'command_input') and self.command_input is not None and self.command_input.hasFocus()
        )
        if target_is_input:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Up:
                    if self.history_index > 0:
                        self.history_index -= 1
                        self.command_input.setText(self.command_history[self.history_index])
                elif event.key() == Qt.Key_Down:
                    if self.history_index < len(self.command_history) - 1:
                        self.history_index += 1
                        self.command_input.setText(self.command_history[self.history_index])
                        return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        # 停止战术模块
        try:
            if hasattr(self, 'biods_enhancer') and self.biods_enhancer:
                if hasattr(self.biods_enhancer, 'stop'):
                    self.biods_enhancer.stop()
        except Exception:
            pass

        # 退出前清理全局键盘钩子/热键，避免驻留
        try:
            if keyboard is not None:
                if getattr(self, '_keyboard_hook', None) is not None:
                    try:
                        keyboard.unhook(self._keyboard_hook)
                    except Exception:
                        pass
                    self._keyboard_hook = None
                if getattr(self, '_keyboard_hotkey', None) is not None:
                    try:
                        keyboard.remove_hotkey(self._keyboard_hotkey)
                    except Exception:
                        pass
                    self._keyboard_hotkey = None
        except Exception:
            pass
        return super().closeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def on_feedback_anchor_clicked(self, url: QUrl):
        """处理反馈区域中的可点击链接，例如取消某个专家任务 或 选择开局预设
        链接格式：
        - 任务取消：task://cancel?task_id=xxxx
        - 开局预设：preset://choose?id=armor_assault|blitzkrieg|firepower_doctrine
        - 预设取消：preset://cancel
        """
        try:
            if not url.isValid():
                return
            scheme = url.scheme()
            # 处理开局预设链接
            if scheme == "preset":
                action = url.host()
                query = url.query() or ""
                params = {}
                for kv in query.split("&"):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        params[k] = v
                # 取消当前预设执行
                if action == "cancel":
                    try:
                        if getattr(self, 'preset_thread', None):
                            self.preset_thread.stop()
                    except Exception:
                        pass
                    # 保持锁定状态，不允许重新选择；仅提示已取消
                    self.add_feedback("开局预设已取消。", "system")
                    return
                # 选择某个预设
                if action == "choose":
                    # 已锁定则忽略
                    if not getattr(self, 'startup_presets_active', False):
                        return
                    preset_id = params.get("id")
                    # 由 _on_preset_selected 内部负责锁定与执行
                    self._on_preset_selected(preset_id)
                return

            # 处理任务相关链接
            if scheme != "task":
                return
            # 解析操作与参数
            action = url.host()
            query = url.query() or ""
            params = {}
            for kv in query.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k] = v
            if action == "cancel":
                tid = params.get("task_id")
                if tid and hasattr(self, 'expert_task_manager') and self.expert_task_manager:
                    ok = self.expert_task_manager.cancel_task(tid)
                    if ok:
                        self.add_feedback(f"已请求取消专家任务 {tid[:8]}…", "system")
                    else:
                        self.add_feedback("取消失败：任务不存在或已结束", "error")
        except Exception as e:
            try:
                self.add_feedback(f"取消操作异常：{e}", "error")
            except Exception:
                pass

    def on_pre_decision_option_changed(self):
        """处理前置决策与模型切换选项变化：
        - 仅控制前置决策是否启用；
        - 切换所用模型（默认flash/可切换普通）。"""
        try:
            pre_enabled = bool(self.enable_predecision_cb.isChecked()) if hasattr(self, 'enable_predecision_cb') else True
            
            # 设置UI控件状态
            if hasattr(self, 'enable_predecision_cb'):
                self.enable_predecision_cb.setEnabled(True)
            if hasattr(self, 'use_flash_predecision_cb'):
                self.use_flash_predecision_cb.setEnabled(True)
            
            # 汇总选择：是否启用前置决策与所用模型
            use_flash_model = bool(self.use_flash_predecision_cb.isChecked()) if hasattr(self, 'use_flash_predecision_cb') else True
            selected_model = "doubao-seed-1-6-flash-250715" if use_flash_model else "doubao-seed-1-6-250615"
            
            # 保护仅剩的相关选项（运行中禁用模型切换）
            try:
                running_predec = bool(getattr(self, 'current_predecision_task_id', None))
                if hasattr(self, 'use_flash_predecision_cb'):
                    self.use_flash_predecision_cb.setEnabled(pre_enabled and (not running_predec))
            except Exception:
                pass
            
            if hasattr(self, 'command_parser') and self.command_parser is not None:
                # 控制是否进入前置决策模型（是否调用LLM）
                setattr(self.command_parser, 'pre_decision_enabled', pre_enabled)
                
                # 仅在“前置决策已启用”时才应用模型切换，并仅在实际发生变化时提示
                try:
                    if pre_enabled and hasattr(self.command_parser, 'pre_decision') and self.command_parser.pre_decision and hasattr(self.command_parser.pre_decision, 'doubao_client') and self.command_parser.pre_decision.doubao_client:
                        prev_model = getattr(self.command_parser.pre_decision.doubao_client, 'model', None)
                        if prev_model != selected_model:
                            self.command_parser.pre_decision.doubao_client.model = selected_model
                except Exception:
                    pass

            # 当取消勾选“前置决策模型”时，若存在正在循环的前置决策任务，则强制取消
            if (not pre_enabled) and getattr(self, 'current_predecision_task_id', None) and hasattr(self, 'expert_task_manager') and self.expert_task_manager:
                try:
                    self.expert_task_manager.cancel_task(self.current_predecision_task_id)
                except Exception:
                    pass
        except Exception as e:
            # UI层静默处理，避免影响主流程
            print(f"[UI] 更新前置决策开关失败: {e}")

    def _poll_expert_task_status(self):
        pass

    def _refresh_recruitment_stats(self):
        try:
            ai = getattr(self.command_parser, 'ai_hq', None)
            if not ai or not hasattr(self, 'arch_tree') or self.arch_tree is None:
                return
            snap = ai.staff.snapshot()
            allies = snap.get('allies') or []
            all_ids = set(int(u.get('id')) for u in allies if isinstance(u.get('id'), int))
            cs = ai.company.snapshot()
            comp_ids = set()
            for name, meta in (cs.get('companies', {}) or {}).items():
                for uid in (meta.get('units') or []):
                    try:
                        comp_ids.add(int(uid))
                    except Exception:
                        pass
            unassigned = len(all_ids - comp_ids) if all_ids else 0
            count = self.arch_tree.topLevelItemCount()
            for i in range(count):
                item = self.arch_tree.topLevelItem(i)
                if item and item.text(0) == "征兵部长":
                    item.setText(1, f"未编入:{unassigned}")
                    break
        except Exception:
            pass

    def _show_arch_tooltip(self):
        try:
            text = str(getattr(self, '_arch_tooltip_text', '') or '')
            pos = getattr(self, '_arch_tooltip_pos', None)
            if text and pos and hasattr(self, 'arch_tree') and self.arch_tree is not None:
                QToolTip.showText(pos, text, self.arch_tree)
        except Exception:
            pass
    
    def _escape_html(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _apply_buff_color(self, desc: str) -> str:
        """根据前缀标记（YYY/XXX/???）为 Buff 文案着色并加粗显示，去除标记本身；其他文本安全转义。"""
        try:
            text = "" if desc is None else str(desc)
        except Exception:
            text = str(desc)
        color = None
        marker = None
        if text.startswith("YYY"):
            marker = "YYY"
            color = "#FF1744"  # 更鲜亮的红色
        elif text.startswith("XXX"):
            marker = "XXX"
            color = "#8E8E93"  # 更醒目的中性灰，与默认灰区分
        elif text.startswith("???"):
            marker = "???"
            color = "#0B0B0B"  # 深黑，强调特殊/未知
        if marker:
            clean = text[len(marker):].lstrip()
            clean_esc = self._escape_html(clean)
            return f'<span style="color:{color}; font-weight:600">{clean_esc}</span>'
        # 无标记：按常规转义
        return self._escape_html(text)
    
    def _build_standardization_html(self, original: str, normalized: str) -> str:
        """构建标准化展示HTML：显示原始与标准化后的命令，并对变更部分高亮。
        仅用于UI展示，不影响命令解析与执行。"""
        o = original or ""
        n = normalized or ""
        sm = difflib.SequenceMatcher(None, o, n)
        parts = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            seg = n[j1:j2]
            if not seg:
                continue
            esc_seg = self._escape_html(seg)
            if tag == 'equal':
                parts.append(esc_seg)
            elif tag == 'insert':
                parts.append(f"<span style='background-color: rgba(76,175,80,0.15); color:#A5D6A7; font-weight:bold;'>{esc_seg}</span>")
            elif tag == 'replace':
                parts.append(f"<span style='color:#4CAF50; font-weight:bold; text-decoration: underline;'>{esc_seg}</span>")
            elif tag == 'delete':
                # 删除在标准化后的文本中不可见，忽略
                pass
        normalized_with_diff = ''.join(parts)
        orig_html = self._escape_html(o)
        return (
            "<div style='margin:4px 0;'>"
            "<div style='color:#B0BEC5; font-size:12px;'>原始: " + orig_html + "</div>"
            "<div style='color:#CFD8DC; font-size:12px;'>标准化(绿色为调整部分): " + normalized_with_diff + "</div>"
            "</div>"
        )
    
    def add_feedback(self, message: str, message_type: str = "normal", task_id: Optional[str] = None):
        """向反馈显示区域追加一条消息。
        支持普通文本与HTML；根据消息类型渲染不同颜色；当提供task_id时，追加可点击的取消链接。
        注意：该方法可能在后台线程中被调用，内部会切换到主线程更新UI。
        """
        try:
            if not hasattr(self, 'feedback_display') or self.feedback_display is None:
                return
            # 颜色映射
            color_map = {
                "system": "#B0BEC5",
                "success": "#A5D6A7",
                "error": "#EF9A9A",
                "command": "#90CAF9",
                "normal": "#CFD8DC",
            }
            color = color_map.get(str(message_type).lower(), "#CFD8DC")
            text = "" if message is None else str(message)
            # 粗略判断HTML
            is_html = ("<" in text and ">" in text)
            if not is_html:
                content = self._escape_html(text) if hasattr(self, '_escape_html') else text
                # 将换行符转换为 <br/>，避免多行文本在HTML中粘连
                content = content.replace("\n", "<br/>")
                html = f"<div style='color:{color}; margin:2px 0;'>{content}</div>"
            else:
                # 已是HTML：仅在非normal类型时包一层颜色容器
                html = text
                if str(message_type).lower() in {"system", "success", "error", "command"}:
                    html = f"<div style='color:{color}; margin:2px 0;'>{html}</div>"
            # 附加取消链接
            if task_id:
                cancel_link = f" <a href=\"task://cancel?task_id={task_id}\" style=\"color:#FFCDD2; text-decoration:none; margin-left:8px;\">[取消]</a>"
                if html.endswith("</div>"):
                    html = html[:-6] + cancel_link + "</div>"
                else:
                    html = html + cancel_link

            # 统一换行处理：确保所有消息都正确换行，解决粘连问题
            msg_type = str(message_type).lower()
            expert_keywords = ["战斗专家", "委托代理", "前置决策", "前置模型", "flash决策", "已提交", "开始分析", "执行完成", "任务", "轮次"]
            is_expert_related = any(k in text for k in expert_keywords)
            
            # 命令输入前插入空行
            if msg_type == "command":
                html = "<br/>" + html
            
            # 专家相关的系统/成功/错误消息：前后都插入空行，避免与其它内容粘连
            if msg_type in ["system", "success", "error"] and is_expert_related:
                html = "<br/>" + html + "<br/>"

            # 额外处理：biods 算法增强相关的系统提示，强制增加空行
            biods_keywords = ["biods算法增强", "biods 算法增强"]
            if msg_type in ["system", "success", "error"] and any(k in text for k in biods_keywords):
                html = "<br/>" + html + "<br/>"
            
            # HTML型的普通消息（多用于标准化展示HTML）后追加空行
            if is_html and msg_type == "normal":
                html = html + "<br/>"

            # 跨线程使用Qt信号在主线程安全更新UI
            self.feedback_html_signal.emit(html)
        except Exception:
            # 静默失败，避免影响主流程
            pass

    def _render_startup_presets(self):
        """在反馈区域渲染开局预设的超链接。"""
        try:
            if not getattr(self, 'startup_presets_active', False):
                return
            html = (
                "<br/>请选择开局策略： "
                "1. <a style='color:#FFA500; font-weight:600;' href=\"preset://choose?id=armor_assault\">装甲集群突击</a>，"
                "2. <a style='color:#1E90FF; font-weight:600;' href=\"preset://choose?id=blitzkrieg\">闪击战</a>，"
                "3. <a style='color:#FF4D4F; font-weight:600;' href=\"preset://choose?id=firepower_doctrine\">优势火力学说</a>"
            )
            self.add_feedback(html, "normal")
        except Exception:
            pass

    def _lock_startup_presets(self):
        """锁定开局预设：禁用所有 preset://choose 链接并显示取消入口。"""
        try:
            if not getattr(self, 'startup_presets_active', False):
                return
            self.startup_presets_active = False
            # 仅禁用选择链接，保留取消可点击
            disable_css = "<style>a[href^='preset://choose']{color:#808080 !important; text-decoration:none !important; pointer-events:none; cursor: default;}</style>"
            suffix = "（已锁定） | <a href=\"preset://cancel\">取消</a>"
            self.add_feedback(disable_css + suffix, "normal")
        except Exception:
            pass

    def _on_preset_selected(self, preset_id: str):
        """选择某个预设后：锁定预设并在后台异步执行固定指令序列。"""
        try:
            self._lock_startup_presets()
            steps = self._get_preset_sequence(str(preset_id or "").strip())
            if not steps:
                return
            # 若已有线程在执行，则不重复启动
            if getattr(self, 'preset_thread', None) and self.preset_thread.isRunning():
                return
            # 启动新的预设执行线程（恢复通用策略，无MCV兜底查询/坐标等待）
            self.preset_thread = PresetRunnerThread(self.command_parser, self.api_client, steps)
            self.preset_thread.start()
        except Exception:
            pass

    def _get_preset_sequence(self, preset_id: str):
        """根据预设ID返回步骤序列：List[Tuple[float, List[str]]] -> (延迟秒, 指令列表)。"""
        pid = (preset_id or "").lower()
        if pid in {"armor_assault", "armor", "aa"}:
            return [
                (0.0, ["展开基地"]),
                (1.0, ["造电厂"]),
                (2.5, ["造兵营"]),
                (3.5, ["造矿场","造5个步枪兵"]),
                (7.5, ["造矿场","步枪兵进攻地图中间"]),
                (7.5, ["造电厂"]),
                (2.5, ["造雷达"]),
                (8.0, ["造机场"]),
                (2.5, ["造雅克", "造矿场"]),
                (7.5, ["造大核电", "雅克进攻"]),
                (3.5, ["造重工"]),
                (11.0, ["雅克攻击电厂", "造2辆矿车", "造维修厂"]),
            ]
        if pid in {"blitzkrieg", "blitz", "bk"}:
            return [
                (0.0, ["展开基地"]),
                (1.0, ["造电厂"]),
                (2.5, ["造3个矿场"]),
                (22.0, ["造电厂"]),
                (2.5, ["造重工"]),
                (11.0, ["造雷达", "造3个防空车"]),
                (8.0, ["造矿场", "造10个V3"]),
                (7.5, ["造大核电"]),
                (3.5, ["造机场"]),
                (3.0, ["造兵营", "造1个雅克"]),
                (3.5, ["造10个步枪兵", "造10个RPG", "造矿场"]),
            ]
        if pid in {"firepower_doctrine", "firepower", "fp"}:
            return [
                (0.0, ["展开基地"]),
                (1.0, ["造电厂"]),
                (2.5, ["造3个矿场"]),
                (22.0, ["造电厂"]),
                (2.5, ["造雷达"]),
                (8.0, ["造大核电"]),
                (3.5, ["造重工"]),
                (11.0, ["造维修厂", "造3个防空车"]),
                (6.5, ["造矿车", "造高科技"]),
                (8.0, ["造3个天启", "造兵营", "造电厂", "造矿场"]),
            ]
        return []

    def _append_feedback_html(self, html: str):
        """实际将HTML插入到反馈显示区（需在主线程调用）。"""
        try:
            if hasattr(self, 'feedback_display') and self.feedback_display:
                # 避免重复追加换行：若传入的html已以<br/>结尾，则不再添加
                safe_html = html or ""
                trimmed = safe_html.rstrip()
                has_trailing_br = trimmed.endswith("<br/>") or trimmed.endswith("<br>")
                self.feedback_display.insertHtml(safe_html + ("" if has_trailing_br else "<br/>"))
                if hasattr(self, 'feedback_display') and hasattr(self.feedback_display, 'moveCursor'):
                    from PyQt5.QtGui import QTextCursor
                    self.feedback_display.moveCursor(QTextCursor.End)
        except Exception:
            pass

    def _on_cp_point_clicked(self, name: str):
        self._cp_selected_name = name
        # 同步更新小地图选中态
        try:
            if hasattr(self, 'cp_minimap') and self.cp_minimap:
                self.cp_minimap.set_selected_name(name)
        except Exception:
            pass
        self._render_cp_buffs()

    def _convert_buffs_to_html(self, buffs: list) -> str:
        if not buffs:
            return "暂无Buff"
        # 将每个 buff 转换为 (分类, 中文描述HTML) 的对，不显示英文代号
        items = []
        for b in buffs:
            cond = b.get("buffName") or b.get("Condition") or b.get("condition") or b.get("name")
            if not cond:
                cond = b.get("desc") or b.get("效果") or "未知Buff"
            entry = BUFF_EFFECT_MAP.get(cond)
            if isinstance(entry, tuple):
                desc, category = entry
            else:
                desc = entry or (b.get("效果") or b.get("desc") or cond)
                category = "其他Buff"
            # 应用颜色标记逻辑（会在内部进行 HTML 转义），不要再二次转义
            items.append((category, self._apply_buff_color(desc)))
        # 去重并保序（按 HTML 文本去重）
        seen = set()
        lines = []
        for cat, desc_html in items:
            key = f"{cat}|{desc_html}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"<p>{self._escape_html(cat)}：{desc_html}。</p>")
        return "".join(lines) if lines else "暂无Buff"

    def _render_cp_buffs(self):
        try:
            if not getattr(self, '_cp_points_cache', None):
                self.cp_buffs_label.setText("暂无Buff")
                return
            # 选中优先，未选中则显示第一个
            name = getattr(self, '_cp_selected_name', None)
            data = None
            if name:
                for p in self._cp_points_cache:
                    if p.get("name") == name or p.get("Name") == name:
                        data = p
                        break
            if data is None and self._cp_points_cache:
                data = self._cp_points_cache[0]
                self._cp_selected_name = data.get("name") or data.get("Name")
            if not data:
                self.cp_buffs_label.setText("暂无Buff")
                return
            buffs = data.get("buffs") or data.get("Buffs") or data.get("buff") or []
            self.cp_buffs_label.setText(self._convert_buffs_to_html(buffs))
        except Exception:
            try:
                self.cp_buffs_label.setText("暂无Buff")
            except Exception:
                pass

    def _poll_control_points(self):
        try:
            # 若未开启“抢据点”模式，直接跳过，确保不会在未勾选状态下后台查询
            if not (hasattr(self, 'enable_cp_cb') and self.enable_cp_cb.isChecked()):
                return
            resp = self.api_client.query_control_points() if hasattr(self, 'api_client') and self.api_client else {}
            # API 返回形如 {"controlPoints": [...]}，详见 README
            points = resp.get("controlPoints") or []
            # 标准化
            norm = []
            for p in points:
                name = p.get("name") or p.get("Name")
                x = p.get("x") if "x" in p else p.get("X")
                y = p.get("y") if "y" in p else p.get("Y")
                owner = p.get("owner") or p.get("Owner")
                buffs = p.get("buffs") or p.get("Buffs") or p.get("buff") or []
                has_buffs_raw = p.get("hasBuffs")
                def _to_bool(v):
                    if isinstance(v, bool):
                        return v
                    if isinstance(v, (int, float)):
                        return v != 0
                    if isinstance(v, str):
                        return v.strip().lower() in ("1", "true", "yes", "y", "t")
                    return False
                has_buffs = _to_bool(has_buffs_raw) if has_buffs_raw is not None else bool(buffs)
                if name is None or x is None or y is None:
                    continue
                norm.append({
                    "name": str(name),
                    "x": float(x),
                    "y": float(y),
                    "owner": owner,
                    "buffs": buffs,
                    "hasBuffs": has_buffs,
                })
            self._cp_points_cache = norm
            # 更新小地图
            try:
                if hasattr(self, 'cp_minimap') and self.cp_minimap:
                    self.cp_minimap.set_points(norm, selected=getattr(self, '_cp_selected_name', None))
            except Exception:
                pass
            # 刷新Buff显示
            self._render_cp_buffs()
        except Exception:
            # 静默失败，避免影响主流程
            pass

class PresetRunnerThread(QThread):
    def __init__(self, command_parser, api_client, steps, parent=None):
        super().__init__(parent)
        self.command_parser = command_parser
        self.api_client = api_client
        # steps: List[Tuple[float, List[str]]] -> (相对延迟秒, 指令列表)
        self.steps = steps or []
        self._running = True

    def run(self):
        try:
            for delay, cmds in self.steps:
                if not self._running:
                    break
                # 先等待相对延迟
                try:
                    d = float(delay or 0)
                except Exception:
                    d = 0.0
                if d > 0:
                    time.sleep(d)

                # 若本步不是“展开基地/基地展开”，则以 Building 队列为空为推进条件
                step_cmds = cmds or []
                is_deploy_step = any(("展开基地" in (c or "")) or ("基地展开" in (c or "")) for c in step_cmds)
                if not is_deploy_step:
                    while self._running:
                        try:
                            data = self.api_client.query_production_queue("Building") or {}
                            items = data.get("queue_items", []) or []
                            # Building 队列为空即可执行下一步
                            if len(items) == 0:
                                break
                        except Exception:
                            # 查询异常时不阻塞整体流程，直接继续执行
                            break
                        # 队列非空，顺延 1 秒后再次查询
                        time.sleep(1.0)
                # 基地展开步骤不做额外等待（恢复旧版行为），直接进入指令执行阶段
                # 执行本步的所有指令（不走 UI 显示，直接解析执行）
                for cmd in step_cmds:
                    if not self._running:
                        break
                    try:
                        # 预设步骤：直接走快速解析（纯关键词->API），不触发任何LLM
                        self.command_parser.parse_command_quick(cmd)
                    except Exception:
                        pass
        except Exception:
            pass

    def stop(self):
        self._running = False
    

# ======================= 据点/BUFF 小地图与映射 =======================
# Buff 中文效果映射（摘自项目 README 表格）
BUFF_EFFECT_MAP = {
    # 通用 Buff
    "cp_dmg_up_150": ("YYY火力大幅提升 （攻击力提升150%）", "通用Buff"),
    "cp_dmg_down_30": ("XXX火力骤降 （攻击力降低70%）", "通用Buff"),
    "cp_armor_30": ("YYY坚固 （受到伤害降低70%）", "通用Buff"),
    "cp_armor_300": ("XXX极度脆弱 （受到伤害增加300%）", "通用Buff"),

    # E1
    "cp_inf_slow": ("迟缓 （移动速度降低80%，攻击速度降低80%）", "E1（步兵）"),
    "cp_inf_berserk": ("狂暴 （攻击力提升500%，移动速度提升100%，受到伤害增加50%）", "E1（步兵）"),
    "cp_inf_accuracy": ("精准 （射程提升100%，攻击力提升200%）", "E1（步兵）"),
    "cp_inf_overheat": ("过热 （装填时间增加100%（射速降低），攻击力降低50%）", "E1（步兵）"),
    "cp_inf_fragile": ("易伤 （受到伤害增加300%）", "E1（步兵）"),

    # RK
    "cp_rkt_slow": ("迟缓 （移动速度降低80%，攻击速度降低80% ）", "RK（火箭兵）"),
    "cp_rkt_rapidfire": ("连发 （五倍射速，攻击力降低20% ）", "RK（火箭兵）"),
    "cp_rkt_overcharge": ("过充 （攻击力提升400%，装填时间增加200% ）", "RK（火箭兵）"),
    "cp_rkt_anti_armor": ("对装强化 （攻击力提升300%，射程提升20% ）", "RK（火箭兵）"),
    "cp_rkt_splash": ("溅射增幅 （攻击力提升80%，射程降低20% ）", "RK（火箭兵）"),
    "cp_rkt_accuracy": ("精准 （射程提升100%，攻击力提升100% ）", "RK（火箭兵）"),
    "cp_rkt_malfunction": ("故障 （攻击力降低70%，装填时间增加200%，射程降低50% ）", "RK（火箭兵）"),
    "cp_rkt_fragile": ("易伤 （受到伤害增加300% ）", "RK（火箭兵）"),

    # V2RL
    "cp_v2_rapidfire": ("YYY连发 （五倍射速，攻击力降低20% ）", "V2RL（V2火箭）"),
    "cp_v2_range_decay": ("XXX射程衰减 （射程降低60%，攻击力提升150% ）", "V2RL（V2火箭）"),
    "cp_v2_overdrive": ("YYY过载 （移动速度提升100%，攻击力提升80% ）", "V2RL（V2火箭）"),
    "cp_v2_guidance_failure": ("XXX制导失效 （攻击力降低75%，射程降低60%，装填时间增加100% ）", "V2RL（V2火箭）"),
    "cp_v2_cant_move": ("XXX定身 （移动速度降低90% ）", "V2RL（V2火箭）"),
    "cp_v2_fragile": ("易伤 （受到伤害增加300% ）", "V2RL（V2火箭）"),

    # FTRK 防空车
    "cp_aa_rapidfire": ("连发 （四倍射速，攻击力提升50% ）", "FTRK（防空车）"),
    "cp_aa_overdrive": ("过载 （移动速度提升50%，攻击力提升180% ）", "FTRK（防空车）"),
    "cp_aa_anti_ground": ("对地强化 （攻击力提升150%，射程提升50% ）", "FTRK（防空车）"),
    "cp_aa_jammed": ("???受干扰 （攻击力降低80%，装填时间增加300%，射程降低70% ）", "FTRK（防空车）"),
    "cp_aa_fragile": ("易伤 （受到伤害增加300% ）", "FTRK（防空车）"),

    # 3TNK 三坦
    "cp_tank_armor_up": ("YYY护甲强化 （受到伤害降低90% ）", "3TNK（三坦）"),
    "cp_tank_super_weak": ("XXX超级衰弱 （攻击力降低80%，受到伤害增加200% ）", "3TNK（三坦）"),
    "cp_tank_ap_rounds": ("YYY穿甲弹 （攻击力提升250%，射程提升20% ）", "3TNK（三坦）"),
    "cp_tank_engine_failure": ("XXX引擎故障 （移动速度降低80%，攻击力降低40%，受到伤害增加100% ）", "3TNK（三坦）"),
    "cp_tank_fragile": ("XXX易伤 （受到伤害增加300% ）", "3TNK（三坦）"),

    # 4TNK 天启
    "cp_mammoth_apex": ("巅峰系统 （攻击力提升200%，移动速度降低20%，射程提升10% ）", "4TNK（天启坦克）"),
    "cp_mammoth_system_overload": ("系统过载 （攻击力降低60%，移动速度降低85%，装填时间增加150% ）", "4TNK（天启坦克）特色"),
    "cp_mammoth_fragile": ("XXX极度易伤 （受到伤害增加500% ）", "4TNK（天启坦克）"),
    "cp_mammoth_super_weak": ("XXX超级衰弱 （攻击力降低80%，受到伤害增加900% ）", "4TNK（天启坦克）"),

    # YAK 雅克
    "cp_yak_anti_infantry": ("反步强化 （攻击力提升100%，移动速度提升20% ）", "YAK（雅克战机）"),
    "cp_yak_chaingun": ("链枪 （攻击力提升80%，装填时间减少70% ）", "YAK（雅克战机）"),
    "cp_yak_jammed": ("受干扰 （攻击力降低90%，移动速度降低90%，装填时间增加400% ）", "YAK（雅克战机）"),
    "cp_yak_fragile": ("易伤 （受到伤害增加300% ）", "YAK（雅克战机）"),
}

class ControlPointMiniMap(QWidget):
    point_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(110, 110))
        self._points = []  # [{name,x,y,hasBuffs}]
        self._selected = None
        self._padding = 6

    def set_points(self, points: list, selected: Optional[str] = None):
        self._points = points or []
        if selected is not None:
            self._selected = selected
        self.update()

    def set_selected_name(self, name: Optional[str]):
        self._selected = name
        self.update()

    def _world_to_view(self, x, y):
        w = max(1, self.width() - 2 * self._padding)
        h = max(1, self.height() - 2 * self._padding)
        max_x = max([p.get('x', 0) for p in self._points] + [100])
        max_y = max([p.get('y', 0) for p in self._points] + [100])
        sx = x / max_x if max_x else 0
        sy = y / max_y if max_y else 0
        vx = self._padding + int(sx * w)
        vy = self._padding + int(sy * h)
        return vx, vy

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 背景
        painter.fillRect(self.rect(), QBrush(QColor(35, 35, 35, 180)))
        # 边框
        pen = QPen(QColor(100, 100, 100, 180))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        # 绘制点
        for p in self._points:
            name = p.get('name', '')
            x, y = int(p.get('x', 0)), int(p.get('y', 0))
            has_buffs = bool(p.get('hasBuffs', False))
            vx, vy = self._world_to_view(x, y)
            r = 4
            color = QColor(30, 144, 255)  # 默认蓝
            if has_buffs:
                color = QColor(255, 165, 0)  # 橙色提示可用Buff
            if self._selected and self._selected == name:
                color = QColor(50, 205, 50)  # 选中绿色
                r = 6
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(vx - r, vy - r, r * 2, r * 2)

    def mousePressEvent(self, event):
        if not self._points:
            return
        ex, ey = event.x(), event.y()
        hit_name = None
        min_dist2 = 999999
        for p in self._points:
            name = p.get('name', '')
            vx, vy = self._world_to_view(int(p.get('x', 0)), int(p.get('y', 0)))
            dx, dy = ex - vx, ey - vy
            d2 = dx * dx + dy * dy
            if d2 < min_dist2 and d2 <= 15 * 15:  # 点击半径阈值
                min_dist2 = d2
                hit_name = name
        if hit_name:
            self.point_clicked.emit(hit_name)

# ======================= ASR 工作线程与协议封装 =======================
class _AsrWorker(QThread):
    text_ready = pyqtSignal(str)
    error_msg = pyqtSignal(str)

    def __init__(self, wav_bytes: bytes, sample_rate: int, appid: str, token: str, cluster: str, ws_url: str, boosting_table_id: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._wav_bytes = wav_bytes
        self._rate = sample_rate
        self._appid = appid
        self._token = token
        self._cluster = cluster
        self._ws_url = ws_url
        self._success_code = 1000
        # 热词词表ID
        self._boosting_table_id = boosting_table_id or ""
        # 分片相关
        self._seg_duration_ms = 15000
        self._nbest = 1

    # --- 协议常量与工具 ---
    PROTOCOL_VERSION = 0b0001
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ACK = 0b1011
    SERVER_ERROR_RESPONSE = 0b1111
    NO_SEQUENCE = 0b0000
    JSON = 0b0001
    GZIP = 0b0001

    def _generate_header(self, message_type=CLIENT_FULL_REQUEST, message_type_specific_flags=NO_SEQUENCE, serial_method=JSON, compression_type=GZIP, extension_header=bytes()):
        header = bytearray()
        header_size = int(len(extension_header) / 4) + 1
        header.append((self.PROTOCOL_VERSION << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(0x00)
        header.extend(extension_header)
        return header

    def _generate_full_default_header(self):
        return self._generate_header()

    def _generate_audio_default_header(self):
        return self._generate_header(message_type=self.CLIENT_AUDIO_ONLY_REQUEST)

    def _generate_last_audio_default_header(self):
        return self._generate_header(message_type=self.CLIENT_AUDIO_ONLY_REQUEST, message_type_specific_flags=0b0010)

    def _parse_response(self, res: bytes):
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size * 4]
        payload = res[header_size * 4:]
        result = {}
        payload_msg = None
        payload_size = 0
        if message_type == self.SERVER_FULL_RESPONSE:
            payload_size = int.from_bytes(payload[:4], "big", signed=True)
            payload_msg = payload[4:]
        elif message_type == self.SERVER_ACK:
            seq = int.from_bytes(payload[:4], "big", signed=True)
            result['seq'] = seq
            if len(payload) >= 8:
                payload_size = int.from_bytes(payload[4:8], "big", signed=False)
                payload_msg = payload[8:]
        elif message_type == self.SERVER_ERROR_RESPONSE:
            code = int.from_bytes(payload[:4], "big", signed=False)
            result['code'] = code
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]
        if payload_msg is None:
            return result
        if message_compression == self.GZIP:
            payload_msg = gzip.decompress(payload_msg)
        if serialization_method == self.JSON:
            payload_msg = json.loads(str(payload_msg, "utf-8"))
        elif serialization_method != 0b0000:
            payload_msg = str(payload_msg, "utf-8")
        result['payload_msg'] = payload_msg
        result['payload_size'] = payload_size
        return result

    @staticmethod
    def _read_wav_info(data: bytes):
        with BytesIO(data) as _f:
            wf = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wf.getparams()[:4]
            wave_bytes = wf.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, len(wave_bytes)

    @staticmethod
    def _slice_data(data: bytes, chunk_size: int):
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        else:
            yield data[offset: data_len], True

    async def _segment_data_processor(self, wav_data: bytes, segment_size: int):
        if not self._appid or not self._token:
            raise RuntimeError("缺少 ASR 凭据：请设置 DOUBAO_ASR_APP_ID 与 DOUBAO_ASR_TOKEN 环境变量")
        reqid = str(uuid.uuid4())
        # full client request
        request_params = {
            'app': {
                'appid': self._appid,
                'cluster': self._cluster,
                'token': self._token,
            },
            'user': {
                'uid': 'openra_asst_asr'
            },
            'request': {
                'reqid': reqid,
                'nbest': self._nbest,
                'workflow': 'audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate',
                'show_language': False,
                'show_utterances': False,
                'result_type': 'full',
                'sequence': 1
            },
            'audio': {
                'format': 'wav',
                'rate': self._rate,
                'language': 'zh-CN',
                'bits': 16,
                'channel': 1,
                'codec': 'raw'
            }
        }
        # 注入热词表ID（若配置）
        if getattr(self, '_boosting_table_id', None):
            try:
                request_params['request']['boosting_table_id'] = self._boosting_table_id
            except Exception:
                pass
        payload_bytes = gzip.compress(str.encode(json.dumps(request_params)))
        full_client_request = bytearray(self._generate_full_default_header())
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)
        header = { 'Authorization': f'Bearer; {self._token}' }
        async with websockets.connect(self._ws_url, additional_headers=header, max_size=1000000000) as ws:
            # send full request
            await ws.send(full_client_request)
            res = await ws.recv()
            result = self._parse_response(res)
            if 'payload_msg' in result and result['payload_msg'].get('code') != self._success_code:
                return result
            for seq, (chunk, last) in enumerate(self._slice_data(wav_data, segment_size), 1):
                payload_bytes = gzip.compress(chunk)
                audio_only_request = bytearray(self._generate_audio_default_header())
                if last:
                    audio_only_request = bytearray(self._generate_last_audio_default_header())
                audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                audio_only_request.extend(payload_bytes)
                await ws.send(audio_only_request)
                res = await ws.recv()
                result = self._parse_response(res)
                if 'payload_msg' in result and result['payload_msg'].get('code') != self._success_code:
                    return result
        return result

    async def _execute(self, wav_bytes: bytes):
        # 直接读取 WAV 信息并按段上传
        nchannels, sampwidth, framerate, nframes, wav_len = self._read_wav_info(wav_bytes)
        size_per_sec = nchannels * sampwidth * framerate
        segment_size = int(size_per_sec * self._seg_duration_ms / 1000)
        return await self._segment_data_processor(wav_bytes, segment_size)

    def run(self):
        try:
            result = asyncio.run(self._execute(self._wav_bytes))
            # 尝试从 payload 中抽取文本
            text = self._extract_text(result)
            if not text:
                # 回显原始结果，便于调试
                self.error_msg.emit(f"ASR未返回文本，原始响应: {json.dumps(result, ensure_ascii=False)[:500]}")
            else:
                self.text_ready.emit(text)
        except Exception as e:
            self.error_msg.emit(f"语音识别异常：{e}")

    def _extract_text(self, result: dict) -> str:
        try:
            payload = result.get('payload_msg') if isinstance(result, dict) else None
            if not isinstance(payload, dict):
                return ""
            # 直出 text（若服务端直接在顶层返回）
            if isinstance(payload.get('text'), str) and payload['text'].strip():
                return payload['text'].strip()
            # 常见字段尝试：result 或 response
            res = payload.get('result') or payload.get('response') or {}
            if isinstance(res, dict):
                if isinstance(res.get('text'), str) and res['text'].strip():
                    return res['text'].strip()
                nbest = res.get('nbest') or res.get('alternatives') or []
                if isinstance(nbest, list) and nbest:
                    cand = nbest[0]
                    if isinstance(cand, dict):
                        for key in ('sentence', 'text', 'transcript'):
                            val = cand.get(key)
                            if isinstance(val, str) and val.strip():
                                return val.strip()
            elif isinstance(res, list):
                # 兼容服务端返回 result 为列表的情形（如 [{"confidence": 0, "text": "基地展开。"}]）
                texts = []
                for item in res:
                    if isinstance(item, dict):
                        for key in ('sentence', 'text', 'transcript'):
                            val = item.get(key)
                            if isinstance(val, str) and val.strip():
                                texts.append(val.strip())
                                break
                if texts:
                    # 中文场景直接拼接
                    return "".join(texts)
            # 兜底：检查 payload 顶层的列表字段
            for list_key in ('nbest', 'alternatives', 'result'):
                lst = payload.get(list_key)
                if isinstance(lst, list):
                    for cand in lst:
                        if isinstance(cand, dict):
                            for key in ('sentence', 'text', 'transcript'):
                                val = cand.get(key)
                                if isinstance(val, str) and val.strip():
                                    return val.strip()
            return ""
        except Exception:
            return ""
    
