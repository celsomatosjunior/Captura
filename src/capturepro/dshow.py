"""Acesso direto ao DirectShow (somente Windows) via comtypes/pygrabber.

- Lista as placas de captura (categoria VideoInputDevice).
- Lê os modos de vídeo REALMENTE anunciados pelo driver (IAMStreamConfig),
  incluindo VIDEOINFOHEADER e VIDEOINFOHEADER2.
- Lê e roteia as entradas físicas do crossbar (IAMCrossbar), quando o
  driver oferece (HDMI/SDI, composto/RCA, S-Video, componente...).

Todas as funções são defensivas: qualquer falha do driver vira uma lista
vazia ou None, nunca derruba o programa.
"""
from __future__ import annotations

import ctypes
import logging
import struct
from ctypes import POINTER, c_long

log = logging.getLogger(__name__)

FORMAT_VIDEOINFO = "{05589F80-C356-11CE-BF01-00AA0055595A}"
FORMAT_VIDEOINFO2 = "{F72A76A0-EB0A-11D0-ACE4-0000C0CC16BA}"
LOOK_UPSTREAM_ONLY = "{AC798BE0-98E3-11D1-B3F1-00AA003761C5}"
IID_IAMCROSSBAR = "{C6E13380-30AC-11D0-A18C-00A0C9118956}"

_RGB_SUBTYPES = {
    "E436EB7D": "RGB24", "E436EB7E": "RGB32", "E436EB7B": "RGB565",
    "E436EB7C": "RGB555", "773C9AC0": "ARGB32", "E436EB7A": "RGB8",
}

PHYS_TYPES = {
    1: "Sintonizador de TV", 2: "Composto (RCA)", 3: "S-Video", 4: "RGB/VGA",
    5: "Componente (YPbPr)", 6: "Digital serial (SDI/HDMI)", 7: "Digital paralelo",
    8: "SCSI", 9: "AUI", 10: "FireWire (1394)", 11: "USB", 12: "Decodificador de vídeo",
    13: "Codificador de vídeo", 14: "SCART", 15: "Preto",
}
PHYS_VIDEO_DECODER = 12

_crossbar_iface = None
_pg = None


def _pygrabber():
    """Importa o pygrabber de forma robusta.

    - Em Windows 'N' sem o Media Feature Pack falta Wmvcore.dll; o pygrabber a
      carrega na importação, mas só a usa para gravação de vídeo (que não
      usamos). Nesse caso fornecemos um módulo vazio no lugar.
    - Desativa o carregamento de perfis de gravação (lento e desnecessário).
    """
    global _pg
    if _pg is None:
        import sys
        import types
        try:
            import pygrabber.windows_media  # noqa: F401
        except OSError as e:
            log.warning("Wmvcore indisponível (%s); seguindo sem perfis de gravação", e)
            fake = types.ModuleType("pygrabber.windows_media")
            fake.IWMPROFILE = object
            fake.IWMProfileManager2 = object
            fake.WMCreateProfileManager = None
            sys.modules["pygrabber.windows_media"] = fake
        from pygrabber import dshow_graph
        dshow_graph.WmProfileManager = lambda: None
        _pg = dshow_graph
    return _pg


def _get_crossbar_iface():
    global _crossbar_iface
    if _crossbar_iface is None:
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

        class IAMCrossbar(IUnknown):
            _iid_ = GUID(IID_IAMCROSSBAR)
            _methods_ = [
                COMMETHOD([], HRESULT, "get_PinCounts",
                          (["out"], POINTER(c_long), "OutputPinCount"),
                          (["out"], POINTER(c_long), "InputPinCount")),
                COMMETHOD([], HRESULT, "CanRoute",
                          (["in"], c_long, "OutputPinIndex"),
                          (["in"], c_long, "InputPinIndex")),
                COMMETHOD([], HRESULT, "Route",
                          (["in"], c_long, "OutputPinIndex"),
                          (["in"], c_long, "InputPinIndex")),
                COMMETHOD([], HRESULT, "get_IsRoutedTo",
                          (["in"], c_long, "OutputPinIndex"),
                          (["out"], POINTER(c_long), "InputPinIndex")),
                COMMETHOD([], HRESULT, "get_CrossbarPinInfo",
                          (["in"], c_long, "IsInputPin"),
                          (["in"], c_long, "PinIndex"),
                          (["out"], POINTER(c_long), "PinIndexRelated"),
                          (["out"], POINTER(c_long), "PhysicalType")),
            ]

        _crossbar_iface = IAMCrossbar
    return _crossbar_iface


def com_init_thread() -> None:
    """Inicializa COM na thread atual (necessário fora da thread da interface)."""
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception as e:  # já inicializado ou modo diferente: tudo bem
        log.debug("CoInitialize: %s", e)


def list_device_names() -> list[str] | None:
    """Nomes das placas de vídeo; None se o DirectShow não puder ser consultado."""
    try:
        names = _pygrabber().FilterGraph().get_input_devices()
        return [str(n) for n in names]
    except Exception as e:
        log.warning("Falha ao listar dispositivos DirectShow: %s", e)
        return None


def subtype_to_fourcc(subtype_guid: str) -> str | None:
    s = subtype_guid.strip("{}").upper()
    data1 = s.split("-")[0]
    if data1 in _RGB_SUBTYPES:
        return _RGB_SUBTYPES[data1]
    if s.endswith("0000-0010-8000-00AA00389B71"):  # GUID FOURCC padrão
        try:
            raw = struct.pack("<I", int(data1, 16))
            txt = raw.decode("ascii")
            if all(32 <= ord(ch) < 127 for ch in txt):
                return txt.strip() or None
        except Exception:
            return None
    return None


def parse_format_block(format_guid: str, block: bytes) -> tuple[int, int, int] | None:
    """Extrai (largura, altura, AvgTimePerFrame) de VIDEOINFOHEADER(2)."""
    g = format_guid.upper()
    if g == FORMAT_VIDEOINFO and len(block) >= 48 + 12:
        avg = struct.unpack_from("<q", block, 40)[0]
        w, h = struct.unpack_from("<ii", block, 52)
    elif g == FORMAT_VIDEOINFO2 and len(block) >= 72 + 12:
        avg = struct.unpack_from("<q", block, 40)[0]
        w, h = struct.unpack_from("<ii", block, 76)
    else:
        return None
    return abs(int(w)), abs(int(h)), int(avg)


def _open_graph(index: int):
    g = _pygrabber().FilterGraph()
    g.add_video_input_device(index)
    return g


def query_modes(index: int) -> list[dict]:
    """Modos anunciados pelo driver: [{width,height,fourcc,min_fps,max_fps,default_fps}]."""
    result: list[dict] = []
    try:
        g = _open_graph(index)
        from pygrabber.dshow_core import IAMStreamConfig
        dev = g.get_input_device()
        sc = dev.get_out().QueryInterface(IAMStreamConfig)
        count, _size = sc.GetNumberOfCapabilities()
        for i in range(count):
            try:
                mt, caps = sc.GetStreamCaps(i)
                m = mt.contents
                fmt = str(m.formattype).upper()
                n = int(m.cbFormat)
                addr = ctypes.cast(m.pbFormat, ctypes.c_void_p).value
                if not addr or n <= 0:
                    continue
                parsed = parse_format_block(fmt, ctypes.string_at(addr, n))
                if not parsed:
                    continue
                w, h, avg = parsed
                if w <= 0 or h <= 0:
                    continue
                min_int = int(getattr(caps, "MinFrameInterval", 0) or 0)
                max_int = int(getattr(caps, "MaxFrameInterval", 0) or 0)
                max_fps = 1e7 / min_int if min_int > 0 else None
                min_fps = 1e7 / max_int if max_int > 0 else None
                default_fps = 1e7 / avg if avg > 0 else max_fps
                result.append({
                    "width": w, "height": h,
                    "fourcc": subtype_to_fourcc(str(m.subtype)),
                    "min_fps": round(min_fps, 3) if min_fps else None,
                    "max_fps": round(max_fps, 3) if max_fps else None,
                    "default_fps": round(default_fps, 3) if default_fps else None,
                })
            except Exception as e:
                log.debug("Capacidade %d ignorada: %s", i, e)
        del sc, dev
        g.remove_filters()
    except Exception as e:
        log.warning("Não foi possível ler os modos do dispositivo %d: %s", index, e)
    return result


def _find_crossbar(g):
    from comtypes import GUID
    IAMCrossbar = _get_crossbar_iface()
    src = g.get_input_device().instance
    res = g.capture_builder.FindInterface(GUID(LOOK_UPSTREAM_ONLY), None, src, GUID(IID_IAMCROSSBAR))
    addr = getattr(res, "value", res)
    if not addr:
        return None
    return ctypes.cast(ctypes.c_void_p(addr), POINTER(IAMCrossbar))


def query_inputs(index: int) -> tuple[list[dict], int | None]:
    """Entradas físicas de vídeo do crossbar: ([{pin, type, label}], pino_atual)."""
    inputs: list[dict] = []
    current = None
    try:
        g = _open_graph(index)
        xb = _find_crossbar(g)
        if xb is None:
            g.remove_filters()
            return [], None
        n_out, n_in = xb.get_PinCounts()
        out_pin = None
        for o in range(n_out):
            _rel, ptype = xb.get_CrossbarPinInfo(0, o)
            if ptype == PHYS_VIDEO_DECODER:
                out_pin = o
                break
        if out_pin is None:
            del xb
            g.remove_filters()
            return [], None
        try:
            current = int(xb.get_IsRoutedTo(out_pin))
        except Exception:
            current = None
        count_by_type: dict[int, int] = {}
        for i in range(n_in):
            _rel, ptype = xb.get_CrossbarPinInfo(1, i)
            if ptype >= 0x1000:  # entradas de áudio
                continue
            count_by_type[ptype] = count_by_type.get(ptype, 0) + 1
            base = PHYS_TYPES.get(ptype, f"Entrada de vídeo (tipo {ptype})")
            inputs.append({"pin": i, "out_pin": out_pin, "type": int(ptype), "label": base})
        # numera entradas repetidas do mesmo tipo
        seen: dict[int, int] = {}
        for item in inputs:
            if count_by_type[item["type"]] > 1:
                seen[item["type"]] = seen.get(item["type"], 0) + 1
                item["label"] += f" {seen[item['type']]}"
        del xb
        g.remove_filters()
    except Exception as e:
        log.info("Dispositivo %d sem crossbar acessível: %s", index, e)
        return [], None
    return inputs, current


def route_input(index: int, out_pin: int, in_pin: int) -> bool:
    try:
        g = _open_graph(index)
        xb = _find_crossbar(g)
        if xb is None:
            return False
        xb.Route(out_pin, in_pin)
        del xb
        g.remove_filters()
        log.info("Entrada %d roteada no dispositivo %d", in_pin, index)
        return True
    except Exception as e:
        log.warning("Falha ao rotear entrada %d: %s", in_pin, e)
        return False
