"""Machinery names are unique among live rows, compared case-insensitively."""
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from machinery.models import MachineModel, MachineType, Manufacturer


class LiveNameUniquenessTests(TestCase):
    def test_a_soft_deleted_name_can_be_added_again(self):
        old = MachineType.objects.create(name="Pump")
        old.delete()
        MachineType.objects.create(name="pump")
        self.assertEqual(MachineType.objects.filter(name__iexact="pump").count(), 1)

    def test_live_duplicates_are_still_refused(self):
        Manufacturer.objects.create(name="CIFA")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Manufacturer.objects.create(name="cifa")

    def test_a_soft_deleted_model_name_can_be_added_again(self):
        kind = MachineType.objects.create(name="Mixer")
        maker = Manufacturer.objects.create(name="Putzmeister")
        MachineModel.objects.create(machine_type=kind, manufacturer=maker, name="M1").delete()
        MachineModel.objects.create(machine_type=kind, manufacturer=maker, name="m1")


class SeedMatchesExistingNamesTests(TestCase):
    def test_seed_reuses_rows_that_differ_only_in_case(self):
        Manufacturer.objects.create(name="cifa")
        MachineType.objects.create(name="concrete pump & mixer")

        call_command("seed_machine_categories", verbosity=0)

        self.assertEqual(Manufacturer.objects.count(), 1)
        self.assertEqual(MachineType.objects.count(), 1)
        self.assertEqual(MachineModel.objects.count(), 4)
