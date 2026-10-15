"""Testes da lógica independente de hardware: processamento, arquivos, configurações."""
import json
import os
import struct

import cv2
import numpy as np
import pytest

from capturepro import processing as P
from capturepro import storage as S
from capturepro.devices import VideoMode, _dedupe_modes, _make_keys
from capturepro.settings import Settings


def img(w=640, h=480):
    rng = np.random.default_rng(1)
    return rng.integers(0, 256, (h, w, 3), dtype=np.uint8)


# ------------------------------------------------------------ processamento
def test_neutral_adjustments_are_bit_exact():
    a = img()
    out = P.apply_adjustments(a, {"brightness": 0, "contrast": 0, "saturation": 0, "sharpness": 0})
    assert np.array_equal(a, out)
    assert np.array_equal(P.process_for_save(a, None, None, None), a)


def test_adjustments_change_image_and_do_not_mutate_input():
    a = img()
    ref = a.copy()
    for key in ("brightness", "contrast", "saturation", "sharpness"):
        out = P.apply_adjustments(a, {key: 40})
        assert not np.array_equal(out, a), key
        assert np.array_equal(a, ref), "a entrada não pode ser modificada"
    bright = P.apply_adjustments(a, {"brightness": 50})
    assert bright.mean() > a.mean()
    gray = P.apply_adjustments(a, {"saturation": -100})
    assert np.abs(gray[..., 0].astype(int) - gray[..., 1]).max() <= 1  # sem cor


def test_crop_uses_real_video_coordinates():
    assert P.crop_to_pixels(1920, 1080, [0.25, 0.5, 0.5, 0.25]) == (480, 540, 1440, 810)
    assert P.crop_to_pixels(1920, 1080, None) == (0, 0, 1920, 1080)
    a = img(1920, 1080)
    c = P.apply_crop(a, [0.25, 0.5, 0.5, 0.25])
    assert c.shape[:2] == (270, 960)
    assert np.array_equal(c, a[540:810, 480:1440])


def test_output_size_preserves_aspect_and_flags_upscale():
    assert P.output_size(1920, 1080, (1280, 720)) == (1280, 720, False)
    w, h, up = P.output_size(1920, 1080, (640, 480))
    assert (w, h, up) == (640, 360, False)          # não deforma
    w, h, up = P.output_size(720, 576, (1920, 1080))
    assert up and h == 1080 and abs(w / h - 720 / 576) < 0.01
    assert P.parse_resolution("custom", 1000, 500) == (1000, 500)
    assert P.parse_resolution("original") is None


def test_full_pipeline_order():
    a = img(1920, 1080)
    out = P.process_for_save(a, [0.1, 0.1, 0.5, 0.5], {"brightness": 10}, (480, 480))
    assert out.shape[:2] == (270, 480)


def test_black_frame_detection():
    assert P.is_black_frame(np.zeros((480, 640, 3), np.uint8))
    assert not P.is_black_frame(img())


# ---------------------------------------------------------------- arquivos
def test_sequential_names_never_overwrite(tmp_path):
    folder = str(tmp_path / "Capturas" / "Endoscopia")
    a = img(320, 240)
    paths = [S.save_image(a, folder, "CAPTURA", "png") for _ in range(3)]
    names = [os.path.basename(p) for p in paths]
    d = S.date_string()
    assert names == [f"CAPTURA_{d}_001.png", f"CAPTURA_{d}_002.png", f"CAPTURA_{d}_003.png"]
    # arquivo pré-existente com número mais alto e outra extensão
    open(os.path.join(folder, f"CAPTURA_{d}_010.jpg"), "wb").write(b"x")
    p = S.save_image(a, folder, "CAPTURA", "png")
    assert os.path.basename(p) == f"CAPTURA_{d}_011.png"
    assert open(os.path.join(folder, f"CAPTURA_{d}_010.jpg"), "rb").read() == b"x"


@pytest.mark.parametrize("fmt,ext", [("png", ".png"), ("jpeg", ".jpg"), ("bmp", ".bmp")])
def test_formats_are_valid_images(tmp_path, fmt, ext):
    a = img(321, 241)
    p = S.save_image(a, str(tmp_path), "TESTE", fmt, 90)
    assert p.endswith(ext)
    back = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    assert back.shape == a.shape
    if fmt in ("png", "bmp"):
        assert np.array_equal(back, a), "PNG/BMP devem ser sem perda"


def test_jpeg_quality_changes_size(tmp_path):
    a = img(640, 480)
    lo = S.encode_image(a, "jpeg", 50)
    hi = S.encode_image(a, "jpeg", 100)
    assert len(hi) > len(lo)


def test_prefix_sanitized_and_unicode_folder(tmp_path):
    assert S.sanitize_prefix('Paciente: João/01*') == "Paciente João01"
    assert S.sanitize_prefix("   ") == "CAPTURA"
    folder = str(tmp_path / "Exames ção ã")
    p = S.save_image(img(64, 64), folder, "Endoscopia João", "png")
    assert os.path.exists(p)
    assert S.count_today(folder, "Endoscopia João") == 1


# ----------------------------------------------------------- configurações
def test_settings_roundtrip_and_per_device(tmp_path):
    path = str(tmp_path / "c.json")
    s = Settings(path)
    s.set("output_folder", "C:\\Capturas\\Endoscopia")
    s.update_device("Placa A", crop=[0.1, 0.2, 0.3, 0.4], adjustments={"brightness": 5},
                    mode={"width": 1280, "height": 720, "fourcc": "YUY2"})
    s.update_device("Placa B", crop=None)
    s.save()
    s2 = Settings(path)
    assert s2.get("output_folder") == "C:\\Capturas\\Endoscopia"
    a = s2.device("Placa A")
    assert a["crop"] == [0.1, 0.2, 0.3, 0.4]
    assert a["adjustments"]["brightness"] == 5 and a["adjustments"]["contrast"] == 0
    assert a["mode"]["width"] == 1280
    assert s2.device("Placa B")["crop"] is None
    assert s2.device("Nunca vista")["crop"] is None


def test_settings_recovers_from_corrupt_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ isto não é json", encoding="utf-8")
    s = Settings(str(path))
    assert s.get("format") == "png"
    s.save()
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "png"
    assert any(n.startswith("c.json.corrompido") for n in os.listdir(tmp_path))


def test_invalid_crop_is_rejected(tmp_path):
    s = Settings(str(tmp_path / "c.json"))
    s.update_device("X", crop=[0.5, 0.5, -1, 2])
    assert s.device("X")["crop"] is None
    s.update_device("X", crop=[0.9, 0.9, 0.5, 0.5])   # ultrapassa a borda → é limitado
    c = s.device("X")["crop"]
    assert abs(c[0] + c[2] - 1.0) < 1e-9 and abs(c[1] + c[3] - 1.0) < 1e-9


# --------------------------------------------------------- dispositivos
def test_dshow_format_parsing():
    from capturepro import dshow
    vih = bytearray(88)
    struct.pack_into("<q", vih, 40, 333333)          # 30 fps
    struct.pack_into("<ii", vih, 52, 1920, -1080)
    assert dshow.parse_format_block(dshow.FORMAT_VIDEOINFO, bytes(vih)) == (1920, 1080, 333333)
    vih2 = bytearray(112)
    struct.pack_into("<q", vih2, 40, 400000)
    struct.pack_into("<ii", vih2, 76, 1280, 720)
    assert dshow.parse_format_block(dshow.FORMAT_VIDEOINFO2, bytes(vih2)) == (1280, 720, 400000)
    assert dshow.parse_format_block("{00000000-0000-0000-0000-000000000000}", bytes(vih)) is None
    assert dshow.subtype_to_fourcc("{32595559-0000-0010-8000-00AA00389B71}") == "YUY2"
    assert dshow.subtype_to_fourcc("{47504A4D-0000-0010-8000-00AA00389B71}") == "MJPG"
    assert dshow.subtype_to_fourcc("{e436eb7d-524f-11ce-9f53-0020af0ba770}") == "RGB24"


def test_modes_dedup_and_fps():
    raw = [
        {"width": 1920, "height": 1080, "fourcc": "MJPG", "min_fps": 5, "max_fps": 60},
        {"width": 1920, "height": 1080, "fourcc": "YUY2", "min_fps": 5, "max_fps": 5},
        {"width": 1920, "height": 1080, "fourcc": "MJPG", "min_fps": 5, "max_fps": 30},
        {"width": 640, "height": 480, "fourcc": "YUY2", "min_fps": 5, "max_fps": 30},
    ]
    modes = _dedupe_modes(raw)
    assert [m.ident() for m in modes] == [(1920, 1080, "YUY2"), (1920, 1080, "MJPG"), (640, 480, "YUY2")]
    assert modes[1].max_fps == 60
    assert modes[1].fps_options()[0] == 60 and 30 in modes[1].fps_options()
    assert "sem compressão" in modes[0].label()
    assert VideoMode(1, 1).fps_options() == []
    assert _make_keys(["Cam", "Cam", "X"]) == ["Cam", "Cam (2)", "X"]
