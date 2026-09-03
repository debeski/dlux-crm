"""
Generated with django-lux 1.2.1.
Project name: switch-pos.
Generated on: 2026-06-22.
"""
import json
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.test import SimpleTestCase

from tools.validate_project_release_manifest import (
    ProjectReleaseManifestError,
    validate_project_release_manifest,
)


class ProjectScaffoldTests(SimpleTestCase):
    def test_settings_uses_dlux_helper(self):
        settings_path = Path(__file__).resolve().parents[1] / "config" / "settings.py"
        contents = settings_path.read_text(encoding="utf-8")
        self.assertIn("from dlux.utils import dlux_settings", contents)
        self.assertIn("dlux_settings(globals())", contents)

    def test_urls_mount_dlux_at_root(self):
        urls_path = Path(__file__).resolve().parents[1] / "config" / "urls.py"
        contents = urls_path.read_text(encoding="utf-8")
        self.assertIn('path("", include("dlux.urls"))', contents)

    def test_failed_update_page_probes_until_caddy_serves_the_app(self):
        page_path = Path(__file__).resolve().parents[1] / ".proxy" / "maintenance.html"
        contents = page_path.read_text(encoding="utf-8")
        self.assertIn("scheduleRecoveryProbe", contents)
        self.assertIn("fetch('/', { cache: 'no-store', credentials: 'same-origin' })", contents)
        self.assertIn("window.location.reload()", contents)

    def test_dlux_requirement_is_an_exact_pin(self):
        """The baked version now comes from the installed package at runtime.

        DjangoLux 1.8.0 retired the ``DLUX_BAKED_VERSION`` entry in
        ``compose.dev.yml`` that this test used to compare against, so the
        requirement pin is the only remaining source to validate.
        """
        project_root = Path(__file__).resolve().parents[1]
        contents = (project_root / "requirements.txt").read_text(encoding="utf-8")
        requirement = re.search(
            r"^django-lux\[updater\]==(?P<version>\d+\.\d+\.\d+)$",
            contents,
            re.MULTILINE,
        )
        self.assertIsNotNone(requirement)

        dev_compose = (project_root / "compose.dev.yml").read_text(encoding="utf-8")
        self.assertNotIn("DLUX_BAKED_VERSION", dev_compose)

    def test_project_release_manifest_matches_image_build_contract(self):
        project_root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_root / "release-manifest.json").read_text(encoding="utf-8")
        )
        project_version = (project_root / "VERSION").read_text(encoding="utf-8").strip()
        validated = validate_project_release_manifest(
            project_root,
            tag=f"v{project_version}",
            repository="debeski/Sales-CRM",
        )

        self.assertEqual(validated, manifest)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["version"], project_version)
        self.assertIsInstance(manifest["summary"], str)
        self.assertLessEqual(len(manifest["summary"]), 1000)
        self.assertLessEqual(len(manifest["highlights"]), 8)
        self.assertTrue(all(len(item) <= 160 for item in manifest["highlights"]))
        self.assertEqual(
            manifest["release_url"],
            f"https://github.com/debeski/Sales-CRM/releases/tag/v{project_version}",
        )

        dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
        workflow = (
            project_root / ".github/workflows/release.yml"
        ).read_text(encoding="utf-8")
        compose = (project_root / "compose.yml").read_text(encoding="utf-8")
        settings = (project_root / "config/settings.py").read_text(encoding="utf-8")
        self.assertIn('ARG DLUX_PROJECT_RELEASE_MANIFEST=""', dockerfile)
        self.assertIn(
            'LABEL org.dlux.project.release-manifest="${DLUX_PROJECT_RELEASE_MANIFEST}"',
            dockerfile,
        )
        self.assertEqual(
            workflow.count(
                "DLUX_PROJECT_RELEASE_MANIFEST=${{ steps.project_manifest.outputs.json }}"
            ),
            2,
        )
        self.assertIn(
            'COMPOSER_RELEASE_MANIFEST_LABEL: "org.dlux.project.release-manifest"',
            compose,
        )
        self.assertIn("DLUX_APP_VERSION = get_project_version(BASE_DIR)", settings)
        self.assertEqual(django_settings.DLUX_APP_VERSION, project_version)
        with self.assertRaisesRegex(ProjectReleaseManifestError, "version mismatch"):
            validate_project_release_manifest(
                project_root,
                tag="v0.0.0",
                repository="debeski/Sales-CRM",
            )
