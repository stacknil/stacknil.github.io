"""Negative controls for the static-site gate; HTTP outcomes are mocked."""
import importlib.util
from http.client import BadStatusLine, InvalidURL
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

    def test_duplicate_attributes_cannot_hide_unsafe_href(self):
        self.mutate('href="#projects"', 'href="javascript:alert(1)" HREF="#projects"')
        self.rejects("duplicate-attribute")

    def test_bare_metadata_attributes_fail_without_traceback(self):
        self.mutate('charset="utf-8"', 'charset')
        self.rejects("metadata")

    def test_backslash_url_paths_are_rejected_on_every_platform(self):
        original = (self.root / "index.html").read_text(encoding="utf-8")
        for value in ("assets\\favicon.svg", "assets%5cfavicon.svg"):
            with self.subTest(value=value):
                (self.root / "index.html").write_text(original.replace("assets/favicon.svg", value), encoding="utf-8")
                self.rejects("unsafe-url")

    def test_quoted_css_imports_are_checked(self):
        css = self.root / "assets/site.css"
        with css.open("a", encoding="utf-8") as stream:
            stream.write('\n@import "imported.css";\n')
        self.rejects("missing-local")
        (self.root / "assets/imported.css").write_text("p { color: inherit; }", encoding="utf-8")
        self.assertEqual(site.validate(self.root), [])

    def test_privacy_diagnostic_never_echoes_sensitive_filename(self):
        value = "gh" + "p_" + "D" * 30
        for text in (value, "Synthetic public content"):
            with self.subTest(content_contains_pattern=text == value):
                issues = site.public_text_issues(value + ".md", text)
                self.assertTrue(issues)
                self.assertNotIn(value, str(issues))

    def test_link_inventory_precedes_all_content_reads(self):
        entry = self.root / "unlinked.md"
        entry.write_text("Synthetic content", encoding="utf-8")
        original = Path.is_symlink
        def linked(path):
            return path == entry or original(path)
        with patch.object(Path, "is_symlink", linked), patch.object(Path, "read_text", side_effect=AssertionError("content read before link rejection")):
            self.rejects("filesystem-link")

    def test_directory_junction_is_rejected_before_content_reads(self):
        entry = self.root / "nested"
        entry.mkdir()
        original = Path.is_junction
        def junction(path):
            return path == entry or original(path)
        with patch.object(Path, "is_junction", junction), patch.object(Path, "read_text", side_effect=AssertionError("content read before junction rejection")):
            self.rejects("filesystem-link")

    def test_directory_index_is_resolved_before_read(self):
        directory = self.root / "nested"
        directory.mkdir()
        page = directory / "index.html"
        page.write_text('<p id="known">Synthetic</p>', encoding="utf-8")
        outside = self.root.parent / "synthetic-outside.html"
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return outside if path == page else original(path, *args, **kwargs)
        issues = []
        with patch.object(Path, "resolve", resolve), patch.object(Path, "read_text", side_effect=AssertionError("read outside tree")):
            site.local_reference(self.root, self.root / "index.html", "nested/#known", issues)
        self.assertTrue(any("outside-root" in issue for issue in issues))

    def symlink_or_skip(self, link, target):
        try:
            link.symlink_to(target)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink privilege unavailable")
            raise

    def test_native_index_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "index.html"
            page = self.root / "index.html"
            target.write_bytes(page.read_bytes())
            page.unlink()
            self.symlink_or_skip(page, target)
            self.rejects("filesystem-link")

    def test_native_unlinked_file_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "public.txt"
            target.write_text("Synthetic public content", encoding="utf-8")
            self.symlink_or_skip(self.root / "unlinked.txt", target)
            self.rejects("filesystem-link")

    def test_native_directory_index_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "index.html"
            target.write_text('<p id="known">Synthetic</p>', encoding="utf-8")
            directory = self.root / "nested"
            directory.mkdir()
            self.symlink_or_skip(directory / "index.html", target)
            self.mutate('href="#projects"', 'href="nested/#known"')
            self.rejects("filesystem-link")

    def test_optional_http_malformed_input_is_inconclusive(self):
        for error in (InvalidURL("synthetic"), ValueError("synthetic"), BadStatusLine("synthetic")):
            with self.subTest(error=type(error).__name__), patch.object(site, "urlopen", side_effect=error):
                self.assertEqual(site.check_external("https://example.com/")[0], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
