"""Stored attachments served by the app instead of the proxy.

Purchase-invoice attachments and expense receipts are supplier and payment
paperwork, so they are read behind the same login, model permission and
ownership checks as their record. ``ProtectedFileField`` points every ``.url``
(the file widget, the detail page, the admin) at ``common:stored_file``, which
answers with DjangoLux's ``serve_file``; Caddy refuses their media paths.
"""
from django.db import models
from django.db.models.fields.files import FieldFile
from django.urls import reverse


class ProtectedFieldFile(FieldFile):
    @property
    def url(self):
        self._require_file()
        if self.instance.pk is None:
            return ""
        opts = self.instance._meta
        return reverse(
            "common:stored_file",
            args=[opts.app_label, opts.model_name, self.instance.pk, self.field.name],
        )


class ProtectedFileField(models.FileField):
    attr_class = ProtectedFieldFile

    def deconstruct(self):
        # Same column, storage and upload path as a plain FileField; reporting it
        # as one keeps the swap out of the migration history.
        name, _path, args, kwargs = super().deconstruct()
        return name, "django.db.models.FileField", args, kwargs
