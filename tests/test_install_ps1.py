"""install.ps1 tiene que poder ejecutarse como "irm | iex" (Windows PowerShell 5.1 y 7).
Acá sólo se comprueban las propiedades estáticas; la ejecución real está en el CI de Windows."""
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "install.ps1"


class InstallPs1Tests(unittest.TestCase):
    def setUp(self):
        self.raw = SCRIPT.read_bytes()
        self.text = self.raw.decode("ascii")  # falla si hay un byte no ASCII

    def test_no_bom_and_ascii(self):
        self.assertFalse(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_no_toplevel_param_or_exit(self):
        # sin param() de primer nivel (iex no puede recibir parámetros) ni exit (cierra la consola)
        self.assertIsNone(re.search(r"^\s*(\[CmdletBinding\(\)\]\s*)?param\(", self.text, re.M | re.I)
                          and re.search(r"\A(?:\s|<#.*?#>)*(\[CmdletBinding\(\)\]\s*)?param\(",
                                        self.text, re.S | re.I))
        self.assertIsNone(re.search(r"^\s*exit\b", self.text, re.M | re.I))

    def test_balanced_braces(self):
        body = re.sub(r"<#.*?#>", "", self.text, flags=re.S)
        body = re.sub(r"'[^'\n]*'|\"(?:`.|[^\"`\n])*\"", "", body)
        body = re.sub(r"#.*", "", body)
        self.assertEqual(body.count("{"), body.count("}"))
        self.assertEqual(body.count("("), body.count(")"))


if __name__ == "__main__":
    unittest.main()
