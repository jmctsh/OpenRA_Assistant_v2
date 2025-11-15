#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
OpenRA 助手程序 - 主入口

这个脚本是OpenRA助手程序的主入口点。
它初始化应用程序，检查游戏是否运行，并启动用户界面。
"""

import sys
import os
import time
import atexit
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from dotenv import load_dotenv

# 导入助手模块
from assistant.ui.main_window import MainWindow
from assistant.api_client import GameAPIClient
from assistant.command_parser import CommandParser
from assistant.unit_mapping import UnitMapper


def main():
    """程序主入口函数"""

    # 加载 .env 文件以支持环境变量配置
    load_dotenv()
    try:
        orig_out = sys.stdout
        orig_err = sys.stderr
        log_path = os.path.join(os.getcwd(), "program.log")
        try:
            open(log_path, "w", encoding="utf-8").close()
        except Exception:
            pass
        f = open(log_path, "a", encoding="utf-8")
        class Tee:
            def __init__(self, streams):
                self.streams = streams
            def write(self, s):
                for st in self.streams:
                    try:
                        st.write(s)
                        st.flush()
                    except Exception:
                        pass
            def flush(self):
                for st in self.streams:
                    try:
                        st.flush()
                    except Exception:
                        pass
        sys.stdout = Tee([orig_out, f])
        sys.stderr = Tee([orig_err, f])
        try:
            atexit.register(f.close)
        except Exception:
            pass
    except Exception:
        pass
    
    # 创建QApplication实例
    app = QApplication(sys.argv)
    app.setApplicationName("OpenRA 助手")
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    
    # 不在启动时检查游戏是否运行，直接创建客户端并打开UI
    api_client = GameAPIClient()

    # 创建单位映射器
    unit_mapper = UnitMapper()
    
    # 创建命令解析器
    command_parser = CommandParser(api_client, unit_mapper)
    
    # 创建主窗口
    main_window = MainWindow(command_parser, api_client)
    main_window.show()
    
    # 运行应用程序事件循环
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
