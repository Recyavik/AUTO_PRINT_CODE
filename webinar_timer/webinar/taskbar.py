"""Своя иконка и имя на панели задач Windows вместо «Python» и значка pythonw.exe.

Одного SetCurrentProcessExplicitAppUserModelID мало: Windows 11 у сгруппированной
кнопки берёт имя и иконку не из окна, а из «приложения» — и для незарегистрированного
AppUserModelID показывает описание и значок pythonw.exe. Поэтому окну дополнительно
записываются свойства оболочки (PKEY_AppUserModel_*): ID, иконка (.ico), имя и
команда перезапуска — их же Windows использует, если кнопку закрепить.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "autoprintcode.webinar-timer"   # постоянный, без версии — иначе каждая версия становится «новым приложением»

_PKEY_FMTID = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
PID_RELAUNCH_COMMAND, PID_RELAUNCH_ICON, PID_RELAUNCH_NAME, PID_APP_ID = 2, 3, 4, 5
_IID_IPROPERTYSTORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
VT_LPWSTR = 31


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        g = cls()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
        return g


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("pwsz", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


# методы IPropertyStore по номеру в vtable
_SET_VALUE = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                ctypes.POINTER(_PROPVARIANT))
_COMMIT = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)
_RELEASE = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def set_process_app_id() -> None:
    """Вызвать до создания первого окна."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except OSError as e:
        log.warning("AppUserModelID не установлен: %s", e)


def relaunch_command() -> str:
    """Команда, которой Windows запустит программу с закреплённой кнопки."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}"'
    gui = exe.with_name("pythonw.exe")
    script = Path(sys.argv[0]).resolve()
    return f'"{gui if gui.exists() else exe}" "{script}"'


def apply_to_window(hwnd: int, icon_path: str, name: str) -> bool:
    """Записать окну AppUserModel-свойства. False — если не получилось (тогда останется значок Python)."""
    shell32 = ctypes.windll.shell32
    store = ctypes.c_void_p()
    try:
        hr = shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(_GUID.of(_IID_IPROPERTYSTORE)),
                                                 ctypes.byref(store))
    except OSError as e:
        log.warning("SHGetPropertyStoreForWindow: %s", e)
        return False
    if hr != 0 or not store:
        return False
    vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value, commit, release = _SET_VALUE(vtbl[6]), _COMMIT(vtbl[7]), _RELEASE(vtbl[2])
    fmtid = _GUID.of(_PKEY_FMTID)
    try:
        # ID записывается последним: при его смене Windows перечитывает остальные свойства
        for pid, value in ((PID_RELAUNCH_COMMAND, relaunch_command()), (PID_RELAUNCH_ICON, icon_path),
                           (PID_RELAUNCH_NAME, name), (PID_APP_ID, APP_ID)):
            set_value(store, ctypes.byref(_PROPERTYKEY(fmtid, pid)), ctypes.byref(_PROPVARIANT(VT_LPWSTR, pwsz=value)))
        commit(store)
        return True
    except OSError as e:
        log.warning("Свойства окна для панели задач не записаны: %s", e)
        return False
    finally:
        release(store)
