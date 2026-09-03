"""Move stored image files into the dlux asset library, in place.

Every `ManagedAssetField` in the project is paired with the plain `ImageField`
it replaces. This walks each pair and, for any row that still has a file but no
asset, adopts that file — the bytes are not copied, the existing storage name
becomes the asset's file, and the row starts pointing at the asset.

The namespace is not guessed: it is the one the asset field itself declares,
which defaults to the model the image was uploaded to in the first place. So a
product photo lands in `catalog.product` and stays out of every other picker.

Dry run by default. Read the report, then pass ``--apply``.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from dlux.assets import adopt_stored_asset
from dlux.forms.asset_fields import managed_asset_fields


def _pairs():
    """``(model, asset_field, legacy_field_name)`` for every field to backfill.

    Declared here rather than discovered: only the project knows which old
    column a given asset field replaced, and guessing by name would quietly skip
    a pair that was named differently.
    """
    from catalog.models import Product, Service
    from public_catalog.models import PublicCatalogListing

    return [
        (Product, "image_asset", "image"),
        (Service, "image_asset", "image"),
        (PublicCatalogListing, "image_override_asset", "image_override"),
    ]


class Command(BaseCommand):
    help = "Adopt stored image files into the dlux asset library (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it the command only reports what it would do.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        total_adopted = 0
        total_skipped = 0

        for model, asset_field_name, legacy_field_name in _pairs():
            field = next(
                (candidate for candidate in managed_asset_fields(model)
                 if candidate.name == asset_field_name),
                None,
            )
            if field is None:
                self.stderr.write(self.style.WARNING(
                    f"{model._meta.label}: no asset field named {asset_field_name}; skipped."
                ))
                continue

            # `all_objects` where the model has it: a soft-deleted row still owns
            # its picture, and leaving it behind would strand the file.
            manager = getattr(model, "all_objects", model._default_manager)
            rows = manager.filter(**{f"{asset_field_name}__isnull": True}).exclude(
                **{legacy_field_name: ""}
            )

            adopted = 0
            skipped = 0
            for row in rows.iterator(chunk_size=200):
                stored = getattr(row, legacy_field_name, None)
                if not stored:
                    continue
                if not apply_changes:
                    adopted += 1
                    self.stdout.write(f"  would adopt {model._meta.label} #{row.pk}: {stored.name}")
                    continue
                with transaction.atomic():
                    asset = adopt_stored_asset(
                        stored,
                        namespace=field.namespace,
                        title=getattr(row, "name", "") or stored.name,
                    )
                    if asset is None:
                        # Missing from storage, or not a valid image any more.
                        skipped += 1
                        self.stderr.write(self.style.WARNING(
                            f"  {model._meta.label} #{row.pk}: {stored.name} could not be adopted."
                        ))
                        continue
                    # update() rather than save(): no audit churn, no signals, and
                    # nothing else on the row is being changed.
                    manager.filter(pk=row.pk).update(**{f"{asset_field_name}_id": asset.pk})
                    adopted += 1

            total_adopted += adopted
            total_skipped += skipped
            verb = "adopted" if apply_changes else "to adopt"
            self.stdout.write(
                f"{model._meta.label}.{legacy_field_name} → {field.namespace}: {adopted} {verb}"
                + (f", {skipped} skipped" if skipped else "")
            )

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(
                f"Adopted {total_adopted} file(s)"
                + (f"; {total_skipped} could not be adopted." if total_skipped else ".")
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {total_adopted} file(s) would be adopted. Re-run with --apply."
            ))
