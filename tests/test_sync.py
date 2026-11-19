"""Sincronía del karaoke (ver tests/sync_harness.py): con marcas del proveedor el error es <= 150 ms en
inicio, medio, final, tras pausa y tras salto, sin deriva; sin marcas se mide y se exige un tope."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from altr import ui
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests.sync_harness import Hablante, informe, medir


@unittest.skipUnless(HAVE_QT, "PySide6 no está instalado")
class SincroniaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = ui.ensure_qapp()

    def correr(self, h, tope, tope_deriva=60):
        res = medir(self.qapp, h)
        informe("", res)
        t = res["_todo"]
        self.assertLessEqual(t["max"], tope, res)
        self.assertLessEqual(abs(t["deriva_ms"]), tope_deriva)

    def test_con_marcas_del_proveedor(self):
        self.correr(Hablante("wav", con_marcas=True, jitter_marcas=0.02), 150)

    def test_wav_sin_marcas_se_alinea_con_el_audio(self):
        self.correr(Hablante("wav"), 450)

    def test_mp3_sin_marcas_se_alinea_con_la_informacion_lateral(self):
        self.correr(Hablante("mp3"), 500)


if __name__ == "__main__":
    unittest.main()
