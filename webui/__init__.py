# WebUI package for Twitch Drops Miner
# Provides a NiceGUI-based web interface as an alternative to the tkinter GUI

from .manager import WebUIManager
from .mock_classes import LoginData

__all__ = ['WebUIManager', 'LoginData']