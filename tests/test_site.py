"""Negative controls for the static-site gate; HTTP outcomes are mocked."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_site", SOURCE / "scripts/validate_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(SOURCE / "index.html", self.root)
        shutil.copytree(SOURCE / "assets", self.root / "assets")

    def mutate(self, old, new):
        path = self.root / "index.html"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def rejects(self, code):
        self.assertTrue(any(code in issue for issue in site.validate(self.root)), code)

    def test_current_site(self):
        self.assertEqual(site.validate(self.root), [])

    def test_missing_navigation_target(self):
        self.mutate('id="projects"', 'id="missing-projects"')
        self.rejects("required-target")

    def test_duplicate_id(self):
        self.mutate('id="projects-title"', 'id="projects"')
        self.rejects("duplicate-id")

    def test_heading_jump(self):
        self.mutate("<h2", "<h3")
        self.mutate("</h2>", "</h3>")
        self.rejects("heading-order")

    def test_unbalanced_markup(self):
        self.mutate("</main>", "</article>")
        self.rejects("markup")

    def test_missing_stylesheet(self):
        self.mutate("assets/site.css", "assets/absent.css")
        self.rejects("missing-local")

    def test_missing_fragment(self):
        self.mutate('href="#projects"', 'href="#absent"')
        self.rejects("missing-fragment")

    def test_local_path_escape(self):
        self.mutate("assets/favicon.svg", "../outside.svg")
        self.rejects("outside-root")

    def test_social_metadata_mismatch(self):
        self.mutate('property="og:url" content="https://stacknil.github.io/"', 'property="og:url" content="https://example.com/"')
        self.rejects("metadata")

    def test_missing_social_image(self):
        (self.root / "assets/social-preview.png").unlink()
        self.rejects("missing-local")

    def test_unsafe_new_tab(self):
        self.mutate('href="https://github.com/stacknil"', 'href="https://github.com/stacknil" target="_blank"')
        self.rejects("new-tab")

    def test_project_typo(self):
        self.mutate("stacknil/LogLens", "stacknil/LogLnes")
        self.rejects("project-link")

    def test_executable_link(self):
        self.mutate('href="#projects"', 'href="javascript:alert(1)"')
        self.rejects("unsafe-url")

    def test_css_reference_is_checked(self):
        with (self.root / "assets/site.css").open("a", encoding="utf-8") as stream:
            stream.write('\nbody { background-image: url("absent.png"); }\n')
        self.rejects("missing-local")

    def test_private_path_in_unlinked_document(self):
        (self.root / "draft.md").write_text("C" + ":\\Users\\example\\private.txt", encoding="utf-8")
        self.rejects("privacy")

    def test_token_in_unlinked_document(self):
        (self.root / "draft.md").write_text("gh" + "p_" + "A" * 30, encoding="utf-8")
        self.rejects("privacy")

    def test_public_urls_are_not_private_drive_paths(self):
        for value in ("https://example.com/", "http://www.w3.org/2000/svg", "https://github.com/stacknil"):
            with self.subTest(value=value):
                self.assertEqual(site.public_text_issues("public.md", value), [])

    def test_privacy_diagnostic_does_not_echo_value(self):
        value = "gh" + "p_" + "B" * 30
        issues = site.public_text_issues("draft.md", value)
        self.assertTrue(issues)
        self.assertNotIn(value, str(issues))

    def test_link_diagnostics_do_not_echo_credential_pattern(self):
        value = "gh" + "p_" + "C" * 30
        self.mutate("assets/favicon.svg", value + ".svg")
        issues = site.validate(self.root)
        self.assertTrue(any("privacy" in item for item in issues))
        self.assertNotIn(value, str(issues))

    def test_encoded_path_escape(self):
        self.mutate("assets/favicon.svg", "%2e%2e/outside.svg")
        self.rejects("outside-root")

    def test_empty_link(self):
        self.mutate('href="#projects"', 'href="#"')
        self.rejects("empty-link")

    def test_missing_motion_rule(self):
        path = self.root / "assets/site.css"
        path.write_text(path.read_text(encoding="utf-8").replace("prefers-reduced-motion", "prefers-unknown"), encoding="utf-8")
        self.rejects("accessibility-css")

    def test_http_success(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(site, "urlopen", return_value=response):
            self.assertEqual(site.check_external("https://example.com/")[0], "VERIFIED")

    def test_http_failure_vs_uncertainty(self):
        for status, expected in ((404, "BROKEN"), (410, "BROKEN"), (403, "UNVERIFIED"), (429, "UNVERIFIED"), (503, "UNVERIFIED")):
            with self.subTest(status=status), patch.object(site, "urlopen", side_effect=HTTPError("https://example.com/", status, "test", {}, None)):
                self.assertEqual(site.check_external("https://example.com/")[0], expected)

    def test_network_failure_is_not_broken(self):
        with patch.object(site, "urlopen", side_effect=URLError("offline")):
            self.assertEqual(site.check_external("https://example.com/")[0], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
