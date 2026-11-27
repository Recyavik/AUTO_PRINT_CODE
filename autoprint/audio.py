"""Звук и микрофоны Windows (1.3, пульт): выключить / включить разом. Core Audio через ctypes (без comtypes).

  • Микрофон «выключить» — все включённые записывающие устройства: настоящий микрофон, NVIDIA Broadcast,
    виртуальные — тебя не слышно нигде, в какой бы программе ни шёл урок.
  • Звук «выключить» — все устройства воспроизведения.
  • «Включить» — те, что выключили мы (их запомнили), и устройство по умолчанию. Запасной микрофон, который
    был выключен ещё до нас, так и остаётся выключенным.

Только из потока интерфейса (там COM уже есть). Нет Core Audio (сервер без звука) — устройств просто нет.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p, wintypes

log = logging.getLogger(__name__)

RENDER, CAPTURE = 0, 1          # EDataFlow
DEVICE_STATE_ACTIVE = 1
CLSCTX_ALL = 0x17
ROLES = (0, 2)                  # eConsole, eCommunications — «по умолчанию» и «для связи»


class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str) -> None:
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(c_wchar_p("{" + s + "}"), byref(self))


CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioEndpointVolume = "5CDF2C82-841E-4546-9722-0CF74078229A"


def _method(obj: c_void_p, index: int, *argtypes):
    """Метод COM-объекта по номеру в таблице (IUnknown — 0..2)."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *a: fn(obj, *a)


def _release(obj) -> None:
    if obj:
        try:
            _method(obj, 2)()
        except OSError:
            pass


class _Endpoint:
    def __init__(self, dev_id: str, vol: c_void_p) -> None:
        self.id = dev_id
        self._vol = vol

    def muted(self) -> bool:
        v = wintypes.BOOL()
        _method(self._vol, 15, POINTER(wintypes.BOOL))(byref(v))          # IAudioEndpointVolume::GetMute
        return bool(v.value)

    def set_muted(self, on: bool) -> None:
        _method(self._vol, 14, wintypes.BOOL, c_void_p)(bool(on), None)   # IAudioEndpointVolume::SetMute

    def close(self) -> None:
        _release(self._vol)
        self._vol = None


class CoreAudio:
    """Настоящие устройства Windows."""

    def _enumerator(self) -> c_void_p:
        ole = ctypes.oledll.ole32
        try:
            ole.CoInitializeEx(None, 2)       # STA; уже есть (поток Qt) — S_FALSE / RPC_E_CHANGED_MODE — не беда
        except OSError:
            pass
        e = c_void_p()
        ole.CoCreateInstance(byref(GUID(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                             byref(GUID(IID_IMMDeviceEnumerator)), byref(e))
        return e

    @staticmethod
    def _dev_id(dev: c_void_p) -> str:
        p = c_wchar_p()
        _method(dev, 5, POINTER(c_wchar_p))(byref(p))                         # IMMDevice::GetId
        s = p.value or ""
        ctypes.windll.ole32.CoTaskMemFree(p)
        return s

    @staticmethod
    def _activate(dev: c_void_p) -> c_void_p:
        vol = c_void_p()
        _method(dev, 3, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(
            byref(GUID(IID_IAudioEndpointVolume)), CLSCTX_ALL, None, byref(vol))   # IMMDevice::Activate
        return vol

    def endpoints(self, flow: int) -> list[_Endpoint]:
        out: list[_Endpoint] = []
        e = self._enumerator()
        coll = c_void_p()
        try:
            _method(e, 3, c_uint, wintypes.DWORD, POINTER(c_void_p))(flow, DEVICE_STATE_ACTIVE, byref(coll))
            n = c_uint()
            _method(coll, 3, POINTER(c_uint))(byref(n))                       # IMMDeviceCollection::GetCount
            for i in range(n.value):
                dev = c_void_p()
                _method(coll, 4, c_uint, POINTER(c_void_p))(i, byref(dev))     # ::Item
                try:
                    out.append(_Endpoint(self._dev_id(dev), self._activate(dev)))
                except OSError as err:          # устройство пропало между перечислением и запросом
                    log.debug("Звук: устройство %d: %s", i, err)
                finally:
                    _release(dev)
        finally:
            _release(coll)
            _release(e)
        return out

    def default_ids(self, flow: int) -> set[str]:
        ids: set[str] = set()
        e = self._enumerator()
        try:
            for role in ROLES:
                dev = c_void_p()
                try:
                    _method(e, 4, c_uint, c_uint, POINTER(c_void_p))(flow, role, byref(dev))  # GetDefaultAudioEndpoint
                    ids.add(self._dev_id(dev))
                except OSError:
                    pass
                finally:
                    _release(dev)
        finally:
            _release(e)
        return ids


class Mute:
    """Выключить / включить звук или микрофоны разом; помнит, что выключили сами."""

    def __init__(self, backend=None) -> None:
        self.backend = backend if backend is not None else CoreAudio()
        self._ours: dict[int, set[str]] = {RENDER: set(), CAPTURE: set()}

    def _eps(self, flow: int) -> list:
        try:
            return self.backend.endpoints(flow)
        except OSError as e:
            log.warning("Звук: устройства не получены: %s", e)
            return []

    @staticmethod
    def _close(eps) -> None:
        for ep in eps:
            close = getattr(ep, "close", None)
            if close:
                close()

    def muted(self, flow: int) -> bool | None:
        """Все включённые устройства выключены — True; хоть одно слышит / играет — False; устройств нет — None."""
        eps = self._eps(flow)
        try:
            states = []
            for ep in eps:
                try:
                    states.append(ep.muted())
                except OSError:
                    pass
            return all(states) if states else None
        finally:
            self._close(eps)

    def set(self, flow: int, off: bool) -> int:
        """off — выключить все; иначе — включить свои и устройство по умолчанию. → сколько устройств изменено."""
        eps = self._eps(flow)
        changed = 0
        try:
            if off:
                for ep in eps:
                    try:
                        if not ep.muted():
                            ep.set_muted(True)
                            self._ours[flow].add(ep.id)
                            changed += 1
                    except OSError as e:
                        log.warning("Звук: %s не выключено: %s", ep.id, e)
            else:
                try:
                    want = self._ours[flow] | self.backend.default_ids(flow)
                except OSError:
                    want = set(self._ours[flow])
                if not want:
                    want = {ep.id for ep in eps}          # ничего не знаем — включить все
                for ep in eps:
                    if ep.id not in want:
                        continue
                    try:
                        if ep.muted():
                            ep.set_muted(False)
                            changed += 1
                    except OSError as e:
                        log.warning("Звук: %s не включено: %s", ep.id, e)
                self._ours[flow].clear()
        finally:
            self._close(eps)
        return changed

    def toggle(self, flow: int) -> bool:
        """Всё выключено — включить, иначе выключить. → выключено ли теперь."""
        off = not bool(self.muted(flow))
        self.set(flow, off)
        return off
