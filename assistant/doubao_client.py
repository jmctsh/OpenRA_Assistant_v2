# -*- coding: utf-8 -*-
"""
豆包 Ark LLM 客户端封装
- 统一关闭深度思考（thinking=disabled）
- 读取 prompt_Ark.txt 中的模型ID说明（由外部设置传入，避免硬编码）
- 提供 chat_json 接口：强制返回纯JSON字符串（不含Markdown与解释）
- 提供系统提示词模板注入（包含兵种克制关系占位符）
"""
from __future__ import annotations
import os
import json
import time
import importlib
from typing import Any, Dict, List, Optional
# Ark SDK 将通过 _load_ark_class() 惰性加载，避免在包未安装时导入失败


class DoubaoClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: Optional[int] = None):
        self.api_key = api_key or os.environ.get("ARK_API_KEY")
        if not self.api_key:
            raise RuntimeError("缺少 Ark API Key，请设置环境变量 ARK_API_KEY 或在构造参数中传入 api_key")
        # 健壮化模型ID读取：避免空字符串导致无效模型
        env_model = (os.environ.get("ARK_MODEL_ID") or "").strip()
        self.model = (model or env_model or "doubao-seed-1-6-250615")
        # 惰性加载 Ark 客户端，避免在包未安装时导入失败
        ArkClass = self._load_ark_class()
        # 读取超时：优先构造参数，其次环境变量 ARK_TIMEOUT（秒），默认 45s
        if timeout is None:
            try:
                timeout = int(os.environ.get("ARK_TIMEOUT", "45").strip())
            except Exception:
                timeout = 45
        self.timeout = timeout
        # 读取思考模式：默认 disabled，可用 enabled/disabled/auto；支持 ARK_THINKING 或 LLM_THINKING 环境变量覆盖
        thinking_type = (os.environ.get("ARK_THINKING") or os.environ.get("LLM_THINKING") or "disabled").strip().lower()
        if thinking_type not in ("enabled", "disabled", "auto"):
            thinking_type = "disabled"
        # 根据官方示例，thinking 参数应该是字典格式
        self.thinking = {"type": thinking_type}
        
        self.client = ArkClass(api_key=self.api_key, timeout=timeout)
        # Debug日志
        self._log_debug(f"DoubaoClient initialized model={self.model} timeout={self.timeout}s thinking={self.thinking}")

    def _debug_enabled(self) -> bool:
        return str(os.environ.get("LLM_DEBUG", "")).strip().lower() in ("1", "true", "yes", "on")

    def _log_debug(self, msg: str) -> None:
        if self._debug_enabled():
            print(f"[LLM_DEBUG] {msg}")

    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 2048, max_completion_tokens: Optional[int] = None) -> str:
        DEFAULT_MAX_TOKENS = 2048
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        # 从环境变量读取全局输出上限覆盖（ARK_MAX_COMPLETION_TOKENS 或 LLM_MAX_COMPLETION_TOKENS）
        mct_env = (os.environ.get("ARK_MAX_COMPLETION_TOKENS") or os.environ.get("LLM_MAX_COMPLETION_TOKENS") or "").strip()
        env_max_completion_tokens: Optional[int] = None
        if mct_env:
            try:
                env_max_completion_tokens = max(0, int(mct_env))
            except Exception:
                env_max_completion_tokens = None

        # 规范化与优先级：显式参数 > 调用方的 max_tokens(非默认) > 环境变量 > 默认值
        def _coerce_int(v) -> Optional[int]:
            try:
                return None if v is None else int(v)
            except Exception:
                return None
        explicit_mct = _coerce_int(max_completion_tokens)
        caller_max_tokens = _coerce_int(max_tokens)
        chosen_source = ""
        if explicit_mct is not None:
            use_max_completion_tokens = max(1, explicit_mct)
            chosen_source = "explicit_max_completion_tokens"
        elif caller_max_tokens is not None and caller_max_tokens != DEFAULT_MAX_TOKENS:
            use_max_completion_tokens = max(1, caller_max_tokens)
            chosen_source = "caller_max_tokens"
        elif env_max_completion_tokens is not None:
            use_max_completion_tokens = max(1, env_max_completion_tokens)
            chosen_source = "env_max_completion_tokens"
        else:
            use_max_completion_tokens = DEFAULT_MAX_TOKENS
            chosen_source = "default"

        # Debug 输入
        self._log_debug(
            f"chat_json start model={self.model} temp={temperature} max_completion_tokens={use_max_completion_tokens} (type={type(use_max_completion_tokens).__name__}, source={chosen_source}) timeout={self.timeout}s thinking={self.thinking}"
        )
        self._log_debug(
            f"system_prompt len={len(system_prompt)} preview={system_prompt[:200].replace('\n',' ')}"
        )
        self._log_debug(
            f"user_prompt len={len(user_prompt)} preview={user_prompt[:200].replace('\n',' ')}"
        )
        t0 = time.time()
        try:
            # 组装参数：统一仅传 max_tokens（与官方示例一致），避免混用导致服务端报错
            params: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "thinking": self.thinking,
                "max_tokens": use_max_completion_tokens,
            }

            # 调用 Ark Chat Completions（遵循官方示例的参数格式）
            resp = self.client.chat.completions.create(**params)
        except Exception as e:
            elapsed = time.time() - t0
            self._log_debug(f"chat_json exception after {elapsed:.2f}s: {type(e).__name__}: {e}")
            raise
        elapsed = time.time() - t0
        # 提取内容
        content = ""
        try:
            content = resp.choices[0].message.content if resp and resp.choices else ""
            self._log_debug(
                f"chat_json done in {elapsed:.2f}s choices={len(resp.choices) if getattr(resp,'choices',None) else 0} content_len={len(content)} preview={str(content)[:200].replace('\n',' ')}"
            )
        except Exception as e:
            self._log_debug(f"chat_json parse response error: {type(e).__name__}: {e}")
            # 尝试打印响应对象的可用属性（避免大量输出）
            try:
                attrs = [k for k in dir(resp) if not k.startswith('_')]
                self._log_debug(f"resp attrs: {attrs[:10]} ...")
            except Exception:
                pass
            raise
        # 强制剥离 Markdown 包裹
        content = str(content).strip()
        if content.startswith("```"):
            content = content.strip('`')
            content = content.replace("json\n", "", 1).strip()
        return content

    @staticmethod
    def build_system_prompt(unit_mapping_text: str, counters_placeholder: str = "{{UNIT_TYPE_COUNTERS}}") -> str:
        """
        构建系统提示词，包含固定格式要求与兵种克制信息。
        - 固定要求：必须返回JSON字符串，且必须包含键 pairs。
        - 不再注入中文-英文单位映射，仅使用英文代码。
        - 动态注入兵种克制内容：counters_placeholder
        """
        lines = [
            "你是一个OpenRA战术分配专家。你的任务是：根据我方作战单位与敌方所有单位的实时坐标与类型，生成逐单位的攻击目标分配。",
            "严格输出要求：只能返回JSON字符串，不要加入任何额外文字、解释或Markdown标记。",
            "输出格式（唯一合法）：必须返回{\"pairs\": [[attacker_id, target_id], ...]}，且仅此一种格式；不得使用其他键名、不得输出分组/对象数组/多余字段。",
            "注意：pairs 必须是二维整数数组；允许多个 attacker_id 指向同一 target_id 以实现集火。",
            "策略：优先基于兵种克制关系，并结合作战规则（优先/就近/集火/穿插/避让）。",
            "兵种克制与规则：",
            counters_placeholder,
        ]
        return "\n".join(lines)

    @staticmethod 
    def get_unit_mapping_text(unit_mapper) -> str:
        # 兼容 UnitMapper 提供的多种接口
        if hasattr(unit_mapper, 'get_mapping_text'):
            return unit_mapper.get_mapping_text()
        # 退化拼装
        if hasattr(unit_mapper, 'code_to_names'):
            lines: List[str] = []
            for code, names in getattr(unit_mapper, 'code_to_names', {}).items():
                if names:
                    names_str = ", ".join(names[:3])
                    lines.append(f"{code}: {names_str}")
            return "\n".join(lines)
        return ""

    @staticmethod
    def _load_ark_class():
        """加载 Ark 客户端类，兼容不同安装方式。
        优先尝试 "volcenginesdkarkruntime"；若失败，提醒安装 volcengine-python-sdk[ark]。
        """
        try:
            mod = importlib.import_module("volcenginesdkarkruntime")
            ArkClass = getattr(mod, "Ark")
            return ArkClass
        except Exception as e:
            # 给出清晰的安装提示，就是在 Conda 环境下
            raise RuntimeError(
                "未找到 Ark Python SDK。请在当前conda环境中安装:\n"
                "  python -m pip install \"volcengine-python-sdk[ark]\"\n"
                "若已安装，请确认使用的是同一个Python/conda环境运行此程序。\n"
                f"原始错误: {e}"
            )

    def chat_json_stream(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 16384, max_completion_tokens: Optional[int] = None):
        """
        流式返回LLM的JSON响应，用于增量解析执行。
        返回生成器，逐块产出 delta.content 内容供增量解析。
        """
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 使用与 chat_json 相同的 token 限制逻辑
        DEFAULT_MAX_TOKENS = 16384  # 流式输出默认更大
        mct_env = (os.environ.get("ARK_MAX_COMPLETION_TOKENS") or os.environ.get("LLM_MAX_COMPLETION_TOKENS") or "").strip()
        env_max_completion_tokens: Optional[int] = None
        if mct_env:
            try:
                env_max_completion_tokens = max(0, int(mct_env))
            except Exception:
                env_max_completion_tokens = None

        def _coerce_int(v) -> Optional[int]:
            try:
                return None if v is None else int(v)
            except Exception:
                return None
        
        explicit_mct = _coerce_int(max_completion_tokens)
        caller_max_tokens = _coerce_int(max_tokens)
        chosen_source = ""
        if explicit_mct is not None:
            use_max_completion_tokens = max(1, explicit_mct)
            chosen_source = "explicit_max_completion_tokens"
        elif caller_max_tokens is not None and caller_max_tokens != DEFAULT_MAX_TOKENS:
            use_max_completion_tokens = max(1, caller_max_tokens)
            chosen_source = "caller_max_tokens"
        elif env_max_completion_tokens is not None:
            use_max_completion_tokens = max(1, env_max_completion_tokens)
            chosen_source = "env_max_completion_tokens"
        else:
            use_max_completion_tokens = DEFAULT_MAX_TOKENS
            chosen_source = "default"

        # Debug 输入
        self._log_debug(
            f"chat_json_stream start model={self.model} temp={temperature} max_completion_tokens={use_max_completion_tokens} (source={chosen_source}) timeout={self.timeout}s thinking={self.thinking}"
        )
        
        t0 = time.time()
        try:
            # 组装参数：关键是 stream=True 和必须包含 thinking 配置
            params: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "thinking": self.thinking,  # 必须关闭深度思考
                "max_tokens": use_max_completion_tokens,
                "stream": True,  # 开启流式输出
            }

            # 调用流式 API
            resp = self.client.chat.completions.create(**params)
            
            # 逐块产出内容
            for chunk in resp:
                # 根据豆包官方示例，检查 choices 并提取 delta.content
                if not chunk.choices:
                    continue
                
                delta_content = chunk.choices[0].delta.content
                if delta_content:
                    yield delta_content
                    
                # 检查是否结束
                if hasattr(chunk.choices[0], 'finish_reason') and chunk.choices[0].finish_reason == 'stop':
                    break
                    
        except Exception as e:
            elapsed = time.time() - t0
            self._log_debug(f"chat_json_stream exception after {elapsed:.2f}s: {type(e).__name__}: {e}")
            raise
            
        elapsed = time.time() - t0
        self._log_debug(f"chat_json_stream completed in {elapsed:.2f}s")