"""Danh sách engine, theo thứ tự hiện trên giao diện."""

from .aiauto import AIAutoGenerateVideo
from .base import Engine
from .broll import StockBRoll
from .hyperframes import HyperFrames
from .mpt import MoneyPrinterTurbo
from .pixelle import PixelleVideo
from .remotion import Remotion
from .whiteboard import Whiteboard


class _Pending(Engine):
    def __init__(self, key: str, label: str, style: str):
        self.key, self.label, self.style = key, label, style

    def check(self):
        return False, "engine đang được tích hợp"


ENGINES: dict[str, Engine] = {
    e.key: e
    for e in (
        MoneyPrinterTurbo(),
        StockBRoll(),
        AIAutoGenerateVideo(),
        HyperFrames(),
        PixelleVideo(),
        Remotion(),
        Whiteboard(),
    )
}
