"""`adopt_image_assets` — moving pre-1.9 stored files into the asset library.

The namespace is not guessed from the file's path or its name. It is the one the
asset field declares, which defaults to the model the image was uploaded to, so
a product photo can only ever land in `catalog.product`.
"""
import tempfile
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from catalog.models import Product, Service

MEDIA = tempfile.mkdtemp(prefix="switchpos-backfill-media-")


def _png_upload(name="p.png", color=(30, 90, 180)):
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class AdoptImageAssetsTests(TestCase):
    def _product(self, name="Lock", image=True):
        return Product.objects.create(
            name=name, cost_usd=Decimal("1"),
            image=_png_upload(f"{name}.png") if image else "",
        )

    def test_dry_run_changes_nothing(self):
        product = self._product()

        call_command("adopt_image_assets")

        product.refresh_from_db()
        self.assertIsNone(product.image_asset)
        self.assertTrue(product.image)

    def test_apply_adopts_into_the_model_s_own_namespace(self):
        product = self._product()
        stored_name = product.image.name

        call_command("adopt_image_assets", "--apply")

        product.refresh_from_db()
        self.assertIsNotNone(product.image_asset)
        self.assertEqual(product.image_asset.namespace, "catalog.product")
        # Adopted in place: the same stored file, not a copy.
        self.assertEqual(product.image_asset.file.name, stored_name)
        self.assertEqual(product.image_url, product.image_asset.url)

    def test_each_model_gets_its_own_pool(self):
        self._product()
        Service.objects.create(name="Install", price_usd=Decimal("5"), image=_png_upload("s.png", (200, 40, 40)))

        call_command("adopt_image_assets", "--apply")

        self.assertEqual(Product.objects.first().image_asset.namespace, "catalog.product")
        self.assertEqual(Service.objects.first().image_asset.namespace, "catalog.service")

    def test_rows_without_a_file_are_left_alone(self):
        product = self._product(image=False)

        call_command("adopt_image_assets", "--apply")

        product.refresh_from_db()
        self.assertIsNone(product.image_asset)

    def test_running_twice_is_a_no_op(self):
        product = self._product()
        call_command("adopt_image_assets", "--apply")
        product.refresh_from_db()
        first_asset = product.image_asset

        call_command("adopt_image_assets", "--apply")

        product.refresh_from_db()
        # Already adopted, so the second pass has nothing to claim.
        self.assertEqual(product.image_asset, first_asset)

    def test_a_row_that_already_has_an_asset_is_not_touched(self):
        product = self._product()
        call_command("adopt_image_assets", "--apply")
        product.refresh_from_db()
        adopted = product.image_asset

        # A stale legacy file left behind must not overwrite the chosen asset.
        Product.objects.filter(pk=product.pk).update(image="catalog/products/stale.png")
        call_command("adopt_image_assets", "--apply")

        product.refresh_from_db()
        self.assertEqual(product.image_asset, adopted)
