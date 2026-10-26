import unittest

from altr.text import clean_text, split_chunks


class CleanTests(unittest.TestCase):
    def test_markdown(self):
        t = "# Título\n\n- **negrita** y `código`\n1. [enlace](http://x.com/a) listo\n> cita"
        out = clean_text(t)
        self.assertNotIn("#", out)
        self.assertNotIn("*", out)
        self.assertNotIn("`", out)
        self.assertIn("enlace listo", out)
        self.assertIn("negrita y código", out)

    def test_urls(self):
        self.assertEqual(clean_text("mirá https://example.com/x?y=1 ahora"), "mirá enlace ahora")
        self.assertIn("https://example.com", clean_text("mirá https://example.com", read_urls=True))

    def test_whitespace_nbsp_crlf(self):
        self.assertEqual(clean_text("a\u00a0b\r\n\r\n\r\n c   d"), "a b\nc d")

    def test_max_chars(self):
        self.assertEqual(len(clean_text("a" * 100, max_chars=10)), 10)

    def test_lexicon_whole_words_case_insensitive(self):
        out = clean_text("GitHub y github, pero no githubber", lexicon={"github": "guitjab"})
        self.assertEqual(out, "guitjab y guitjab, pero no githubber")


class ChunkTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(split_chunks(""), [])
        self.assertEqual(split_chunks("   \n "), [])

    def test_short_single(self):
        self.assertEqual(split_chunks("Hola mundo."), ["Hola mundo."])

    def test_first_chunk_is_short_and_no_loss(self):
        text = " ".join(f"Esta es la oración número {i}, con algo de relleno." for i in range(30))
        chunks = split_chunks(text, first_max=160, max_chars=400)
        self.assertLessEqual(len(chunks[0]), 160)
        self.assertTrue(all(len(c) <= 400 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_very_long_sentence_is_split_on_words(self):
        text = ("palabra " * 200).strip() + "."
        chunks = split_chunks(text, first_max=100, max_chars=200)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_newlines_split(self):
        self.assertEqual(split_chunks("uno\ndos\ntres", first_max=5, max_chars=5), ["uno", "dos", "tres"])


if __name__ == "__main__":
    unittest.main()
