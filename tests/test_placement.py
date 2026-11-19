"""Lógica de posición del overlay (sin Qt)."""
import json
import tempfile
import unittest
from pathlib import Path

from altr import placement as P
from altr.placement import Rect

SCREEN = Rect(0, 0, 1920, 1080)
WORK_BAR_BOTTOM = Rect(0, 0, 1920, 1040)      # barra de tareas abajo (40 px)
WORK_BAR_TOP = Rect(0, 40, 1920, 1040)        # barra de tareas arriba


class AnchorTests(unittest.TestCase):
    def test_top_center_sits_under_a_top_taskbar(self):
        x, y = P.anchor_xy("top-center", WORK_BAR_TOP, 704, 300)
        self.assertEqual((x, y), (608, 40))       # la ventana empieza en el área de trabajo, no bajo la barra

    def test_bottom_center_sits_above_a_bottom_taskbar(self):
        x, y = P.anchor_xy("bottom-center", WORK_BAR_BOTTOM, 704, 300)
        self.assertEqual(y + 300, 1040)

    def test_corners_keep_the_gap(self):
        self.assertEqual(P.anchor_xy("top-left", WORK_BAR_TOP, 704, 300)[0], P.HUECO)
        self.assertEqual(P.anchor_xy("top-right", WORK_BAR_TOP, 704, 300)[0], 1920 - 704 - P.HUECO)

    def test_second_monitor_with_offset(self):
        work = Rect(1920, 0, 2560, 1400)
        x, y = P.anchor_xy("top-center", work, 704, 300)
        self.assertEqual((x, y), (1920 + (2560 - 704) // 2, 0))


class PinTests(unittest.TestCase):
    def test_round_trip(self):
        pin = P.pin_from_window(300, 500, 704, SCREEN)
        self.assertEqual(P.window_from_pin(pin, 704, 300, SCREEN, WORK_BAR_BOTTOM), (300, 500))

    def test_resolution_change_scales_and_taskbar_clamps(self):
        pin = P.pin_from_window(608, 0, 704, SCREEN)          # arriba, centrado, en 1920x1080
        big = Rect(0, 0, 3840, 2160)
        work = Rect(0, 80, 3840, 2080)                        # ahora la barra está arriba
        x, y = P.window_from_pin(pin, 704, 300, big, work)
        self.assertEqual(y, 80)                               # no queda bajo la barra
        self.assertEqual(x, 1568)                             # sigue centrada: 3840/2 - 352

    def test_pin_cannot_leave_the_work_area(self):
        pin = {"x": 1.0, "y": 1.0}
        x, y = P.window_from_pin(pin, 704, 300, SCREEN, WORK_BAR_BOTTOM)
        self.assertEqual((x + 704, y + 300), (1920, 1040))

    def test_valid_pin(self):
        self.assertTrue(P.valid_pin({"x": 0.5, "y": 0}))
        for bad in (None, {}, {"x": 2, "y": 0}, {"x": "a", "y": 0}, [1, 2], {"x": 0.5}):
            self.assertFalse(P.valid_pin(bad), bad)


class DragTests(unittest.TestCase):
    def test_threshold(self):
        self.assertFalse(P.exceeds_threshold(3, 4))           # 5 px: todavía un clic
        self.assertFalse(P.exceeds_threshold(6, 0))
        self.assertTrue(P.exceeds_threshold(5, 5))

    def test_follows_cursor_keeping_the_grab_point(self):
        d = P.Drag((700, 120), (600, 100))
        self.assertEqual(d.move((800, 320), 704, 300, WORK_BAR_BOTTOM), (700, 300))
        self.assertTrue(d.moved)

    def test_no_move_no_flag(self):
        d = P.Drag((700, 120), (300, 100))
        d.move((700, 120), 704, 300, WORK_BAR_BOTTOM)
        self.assertFalse(d.moved)

    def test_clamped_to_work_area(self):
        d = P.Drag((700, 120), (600, 100))
        self.assertEqual(d.move((-5000, 9000), 704, 300, WORK_BAR_BOTTOM), (0, 740))

    def test_snaps_to_center(self):
        d = P.Drag((700, 120), (600, 100))
        x, _ = d.move((700 + 8 + 8, 120), 704, 300, WORK_BAR_BOTTOM)   # 608 + 16 = 8 px largos del centro
        self.assertEqual(x, 608)
        x, _ = d.move((700 + 100, 120), 704, 300, WORK_BAR_BOTTOM)
        self.assertEqual(x, 700)


class StoreTests(unittest.TestCase):
    def test_save_load_clear_per_monitor(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "pos.json"
            s = P.PosStore(p)
            s.set(r"\\.\DISPLAY1", {"x": 0.25, "y": 0.5})
            s.set(r"\\.\DISPLAY2", {"x": 0.5, "y": 0.1})
            s2 = P.PosStore(p)
            self.assertEqual(s2.get(r"\\.\DISPLAY1"), {"x": 0.25, "y": 0.5})
            self.assertTrue(s2.clear(r"\\.\DISPLAY1"))
            self.assertFalse(s2.clear(r"\\.\DISPLAY1"))
            s3 = P.PosStore(p)
            self.assertIsNone(s3.get(r"\\.\DISPLAY1"))
            self.assertEqual(s3.get(r"\\.\DISPLAY2"), {"x": 0.5, "y": 0.1})
            self.assertFalse(p.with_name("pos.json.tmp").exists())

    def test_broken_or_foreign_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pos.json"
            p.write_text("{no es json", encoding="utf-8")
            self.assertEqual(P.PosStore(p).data, {})
            p.write_text(json.dumps({"A": {"x": 0.5, "y": 0.5}, "B": {"x": 9, "y": 0}, "C": 3}), encoding="utf-8")
            self.assertEqual(list(P.PosStore(p).data), ["A"])
            p.write_text("[1,2]", encoding="utf-8")
            self.assertEqual(P.PosStore(p).data, {})


if __name__ == "__main__":
    unittest.main()
