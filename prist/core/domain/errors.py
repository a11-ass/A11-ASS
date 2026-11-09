"""领域层异常。"""

from __future__ import annotations


class ConfigurationError(Exception):
    """配置文件缺失或格式错误。"""
