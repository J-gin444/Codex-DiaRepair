"""Scanner 模块的异常定义。所有异常都继承自 ScannerError。"""


class ScannerError(Exception):
    """Scanner 模块的基础异常。"""
    pass


class ConfigParseError(ScannerError):
    """config.toml 解析失败。"""
    pass


class DatabaseError(ScannerError):
    """SQLite 数据库读取失败。"""
    pass


class SessionFileError(ScannerError):
    """会话文件读取失败（单个文件，不中断整体流程）。"""
    pass
