"""Opção 'Iniciar com o Windows' (chave Run do usuário atual)."""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CapturePro"


def supported() -> bool:
    return sys.platform == "win32"


def executable_path() -> str:
    """Caminho do CapturePro.exe (o lançador define CAPTUREPRO_EXE)."""
    return os.environ.get("CAPTUREPRO_EXE") or sys.executable


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, f'"{executable_path()}"')
            else:
                try:
                    winreg.DeleteValue(k, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        log.error("Falha ao alterar inicialização automática: %s", e)
        return False
