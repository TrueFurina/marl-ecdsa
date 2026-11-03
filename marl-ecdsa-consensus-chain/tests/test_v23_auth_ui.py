"""V23 authentication page regression checks: no Flask server needed."""
import re
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

BASE = Path(__file__).resolve().parents[1]

class AuthPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(BASE / "templates")), autoescape=True)
        cls.template = cls.env.get_template("auth.html")

    def render(self, mode):
        return self.template.render(
            mode=mode,
            csrf_token=lambda: "TEST_CSRF_TOKEN",
            get_flashed_messages=lambda with_categories: [],
        )

    def test_login_form_keeps_server_contract(self):
        html = self.render("login")
        self.assertIn('action="/login"', html)
        for name in ("username", "password", "csrf_token"):
            self.assertIn(f'name="{name}"', html)
        self.assertNotIn('name="confirm"', html)
        self.assertIn('value="TEST_CSRF_TOKEN"', html)

    def test_register_form_keeps_server_contract(self):
        html = self.render("register")
        self.assertIn('action="/register"', html)
        for name in ("username", "password", "confirm", "csrf_token"):
            self.assertIn(f'name="{name}"', html)
        self.assertIn('maxlength="128"', html)

    def test_no_duplicate_dom_ids(self):
        for mode in ("login", "register"):
            with self.subTest(mode=mode):
                ids = re.findall(r'\bid="([^"]+)"', self.render(mode))
                self.assertEqual(len(ids), len(set(ids)))

    def test_assets_and_reduced_motion(self):
        html = self.render("login")
        self.assertIn('/static/auth.css?v=23', html)
        self.assertIn('/static/auth.js?v=24', html)
        css = (BASE / "static" / "auth.css").read_text(encoding="utf-8")
        self.assertIn('prefers-reduced-motion:reduce', css)
        js = (BASE / "static" / "auth.js").read_text(encoding="utf-8")
        self.assertIn('checkValidity()', js)
        self.assertIn('data-reveal', js)

if __name__ == "__main__":
    unittest.main()
