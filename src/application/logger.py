"""简单日志记录器。GUI 和 CLI 共用。"""

from datetime import datetime

class Logger:
    def __init__(self):
        self._messages: list[str] = []
        self._callback = None

    def on_message(self, callback):
        self._callback = callback

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = "[%s] %s" % (ts, msg)
        self._messages.append(line)
        if self._callback:
            self._callback(line)

    def get_all(self) -> list[str]:
        return list(self._messages)

    def clear(self):
        self._messages.clear()
