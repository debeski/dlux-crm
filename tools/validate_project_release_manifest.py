"""Validate project release metadata before building a tagged image."""

import argparse
import base64
import json
import os
from pathlib import Path


class ProjectReleaseManifestError(ValueError):
    """Raised when project release metadata cannot be safely published."""


def encode_project_release_manifest_label(manifest):
    """Encode validated JSON for quote-safe transport through Docker build args."""
    compact = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True)
    encoded = base64.urlsafe_b64encode(compact.encode("utf-8")).decode("ascii")
    return f"base64:{encoded}"


def _tag_version(tag):
    value = str(tag or "").strip()
    if value.startswith("refs/tags/"):
        value = value.removeprefix("refs/tags/")
    return value.removeprefix("v")


def validate_project_release_manifest(project_root, tag, repository):
    project_root = Path(project_root)
    manifest_path = project_root / "release-manifest.json"
    version_path = project_root / "VERSION"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_version = version_path.read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectReleaseManifestError(str(exc)) from exc

    if not isinstance(manifest, dict):
        raise ProjectReleaseManifestError("release-manifest.json must contain a JSON object")

    errors = []
    schema_version = manifest.get("schema_version")
    manifest_version = manifest.get("version")
    summary = manifest.get("summary")
    highlights = manifest.get("highlights")
    release_url = manifest.get("release_url")
    tag_version = _tag_version(tag)

    if isinstance(schema_version, bool) or schema_version != 1:
        errors.append("release-manifest.json must use schema_version 1")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        errors.append("release-manifest.json requires a non-empty version")
    elif len(manifest_version.strip()) > 64:
        errors.append("release-manifest.json version exceeds 64 characters")
    if manifest_version != file_version or manifest_version != tag_version:
        errors.append(
            f"version mismatch: manifest={manifest_version!r}, "
            f"VERSION={file_version!r}, tag={tag_version!r}"
        )
    if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 1000:
        errors.append("release-manifest.json summary must contain 1-1000 characters")
    if not isinstance(highlights, list) or not 1 <= len(highlights) <= 8:
        errors.append("release-manifest.json highlights must contain 1-8 items")
    elif any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > 160
        for item in highlights
    ):
        errors.append("each release-manifest.json highlight must contain 1-160 characters")

    repository = str(repository or "").strip()
    expected_url = (
        f"https://github.com/{repository}/releases/tag/v{manifest_version}"
        if repository
        else ""
    )
    if not expected_url or release_url != expected_url:
        errors.append(f"release_url must be {expected_url!r}")

    if errors:
        raise ProjectReleaseManifestError("\n".join(errors))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", default=os.getenv("GITHUB_REF_NAME", ""))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    args = parser.parse_args(argv)

    try:
        manifest = validate_project_release_manifest(
            args.project_root,
            tag=args.tag,
            repository=args.repository,
        )
    except ProjectReleaseManifestError as exc:
        for error in str(exc).splitlines():
            print(f"::error::{error}")
        return 1

    compact = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True)
    label = encode_project_release_manifest_label(manifest)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as output:
            output.write(f"json={compact}\n")
            output.write(f"label={label}\n")
    print(f"Validated project release manifest v{manifest['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
