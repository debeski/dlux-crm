"""
Generated with django-lux 1.2.1.
Project name: switch-pos.
Generated on: 2026-06-22.
"""
import base64
import json
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.test import SimpleTestCase

from tools.validate_project_release_manifest import (
    ProjectReleaseManifestError,
    encode_project_release_manifest_label,
    validate_project_release_manifest,
)


def service_block(compose, name):
    services = re.search(r"^services:\n(.*?)(?=^\S|\Z)", compose, re.M | re.S).group(1)
    return re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", services, re.M | re.S).group(1)


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

    def test_maintenance_page_comes_from_composer(self):
        """Stack schema 3: composer-agent publishes the page on the runtime volume."""
        project_root = Path(__file__).resolve().parents[1]
        self.assertFalse((project_root / ".proxy" / "maintenance.html").exists())
        compose = (project_root / "compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("maintenance.html", compose)
        self.assertIn("dlux_runtime:/opt/dlux-runtime:ro", compose)
        caddyfile = (project_root / ".proxy" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("handle /_dlux/maintenance/* {", caddyfile)
        self.assertIn("root * /opt/dlux-runtime/proxy/maintenance", caddyfile)
        self.assertIn("rewrite * /index.html", caddyfile)
        self.assertNotIn("/usr/share/caddy/maintenance", caddyfile)

    def test_stack_files_carry_the_installed_contract_schema(self):
        from dlux.contracts.stack import stack_schema

        project_root = Path(__file__).resolve().parents[1]
        expected = str(stack_schema())
        self.assertIn(f'DLUX_STACK_SCHEMA: "{expected}"', (project_root / "compose.yml").read_text(encoding="utf-8"))
        self.assertIn(
            f'LABEL org.dlux.stack-schema="{expected}"', (project_root / "Dockerfile").read_text(encoding="utf-8")
        )
        for name in ("compose.dev.yml", "entrypoint.sh", "gunicorn.py", ".proxy/Caddyfile", "deploy/env.template"):
            with self.subTest(file=name):
                self.assertIn(f"# dlux stack schema {expected}\n", (project_root / name).read_text(encoding="utf-8"))

    def test_wrappers_match_the_dlux_scaffold(self):
        """start.sh/start.ps1 are the installed DjangoLux's scaffold wrappers, byte for byte."""
        import dlux

        project_root = Path(__file__).resolve().parents[1]
        templates = Path(dlux.__file__).resolve().parent / "scaffold" / "templates" / "project"
        for name in ("start.sh", "start.ps1"):
            with self.subTest(wrapper=name):
                self.assertEqual(
                    (project_root / name).read_bytes(),
                    (templates / f"{name}.tmpl").read_bytes(),
                )

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
        self.assertEqual(requirement.group("version"), "1.16.1")
        self.assertEqual(contents.count("django-lux"), 1, "one pin line, no wheel URL beside it")
        self.assertNotIn("files.pythonhosted.org", contents)

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
            repository="debeski/dlux-crm",
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
            f"https://github.com/debeski/dlux-crm/releases/tag/v{project_version}",
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
                "DLUX_PROJECT_RELEASE_MANIFEST=${{ steps.project_manifest.outputs.label }}"
            ),
            2,
        )
        label = encode_project_release_manifest_label(manifest)
        self.assertTrue(label.startswith("base64:"))
        self.assertNotIn('"', label)
        self.assertEqual(
            json.loads(base64.urlsafe_b64decode(label.removeprefix("base64:"))),
            manifest,
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
                repository="debeski/dlux-crm",
            )

    def test_worker_runs_dlux_tasks_beside_the_project_celery_service(self):
        project_root = Path(__file__).resolve().parents[1]
        compose = (project_root / "compose.yml").read_text(encoding="utf-8")
        worker = service_block(compose, "worker")
        celery = service_block(compose, "celery")
        self.assertIn('"python", "manage.py", "dlux_worker"]', worker)
        self.assertIn('"dlux_worker", "--check"]', worker)
        self.assertIn("stop_grace_period: 30s", worker)
        self.assertIn('DLUX_BOOT_GATE: "apply"', worker)
        self.assertIn("pre_start:", worker)
        self.assertIn("dlux_reconcile", worker)
        self.assertIn("manage.py migrator", worker)
        self.assertIn("dlux_runtime:/opt/dlux-runtime:rw", worker)
        self.assertIn('"-m", "celery", "-A", "config", "worker", "-B"', celery)
        self.assertNotIn("pre_start:", celery)
        self.assertNotIn("DLUX_BOOT_GATE", celery)
        self.assertIn("dlux_runtime:/opt/dlux-runtime:rw", celery)
        self.assertNotIn("- egress", celery, "the rate scrape goes through the Composer relay")
        self.assertIn("      - internal", celery)
        self.assertEqual(compose.count('COMPOSER_AGENT_RESTART_SERVICES: "web,worker,celery,smtp-relay,caddy"'), 2)

    def test_db_environment_is_not_the_shared_application_block(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yml").read_text(encoding="utf-8")
        db = service_block(compose, "db")
        self.assertNotIn("<<: *de", db)
        self.assertIn("POSTGRES_DB:", db)
        self.assertNotIn("DLUX_STACK_SCHEMA", db)
        self.assertNotIn("WEB_IMAGE", db)

    def test_boot_gate_lets_only_the_worker_apply_migrations(self):
        project_root = Path(__file__).resolve().parents[1]
        entrypoint = (project_root / "entrypoint.sh").read_text(encoding="utf-8")
        for marker in (
            'case "${DLUX_BOOT_GATE:-on}" in',
            "  off)",
            "  apply)",
            "manage.py migrate --check",
            "manage.py migrate --noinput",
            'exec "$@"',
        ):
            self.assertIn(marker, entrypoint, marker)
        self.assertNotIn("DLUX_BOOT_GATE", service_block(
            (project_root / "compose.yml").read_text(encoding="utf-8"), "web"))

    def test_front_proxy_is_trusted_through_dlux_front_proxy_and_never_set_in_shipped_files(self):
        project_root = Path(__file__).resolve().parents[1]
        caddy = (project_root / ".proxy" / "Caddyfile").read_text(encoding="utf-8")
        compose = (project_root / "compose.yml").read_text(encoding="utf-8")
        template = (project_root / "deploy" / "env.template").read_text(encoding="utf-8")
        self.assertIn("trusted_proxies static {$DLUX_FRONT_PROXY:private_ranges}", caddy)
        self.assertIn('DLUX_FRONT_PROXY: "${DLUX_FRONT_PROXY-private_ranges}"', service_block(compose, "caddy"))
        self.assertIn("\n# DLUX_FRONT_PROXY=", template)
        self.assertNotRegex(template, r"(?m)^DLUX_FRONT_PROXY=")

    def test_resident_composer_commands_use_the_run_form(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yml").read_text(encoding="utf-8")
        self.assertRegex(service_block(compose, "composer-agent"), r"command:\n      - agent\n      - run\n")
        self.assertRegex(service_block(compose, "composer-executor"), r"command:\n      - executor\n      - run\n")
