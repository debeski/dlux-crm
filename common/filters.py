"""Shared filter building blocks.

Two things every list wants and none of them had: a date range, and a year to
jump to. The register goes back years, so scrolling to find one is not a search
strategy.

The year dropdown is built from the dates actually present rather than from a
fixed range: a filter offering years with nothing behind them is worse than no
filter.
"""
import django_filters
from django.db.models import DateTimeField

from .i18n import t


def year_choices(queryset, field_name):
    """``[(year, year)]`` newest first, for the years the data actually holds.

    ``.dates()`` rather than an ExtractYear annotation: it is one indexed
    DISTINCT the database already knows how to answer.

    Takes a queryset, not a model, so the years come from the rows this user can
    already see. Reading the default manager instead would list years belonging
    to another scope's or another rep's records — the dropdown would report that
    data exists without ever showing it.
    """
    return [
        (str(entry.year), str(entry.year))
        for entry in queryset.dates(field_name, "year", order="DESC")
    ]


class DatedFilterSet(django_filters.FilterSet):
    """Adds ``year``, ``date_gte`` and ``date_lte`` on the model's main date.

    ``date_field`` names it. dlux's ``set_field_attrs`` recognises the
    ``_gte``/``_lte`` suffixes and labels them From/To in the active language, so
    the names are not arbitrary.
    """

    #: The date a user means when they say "when" for this model.
    date_field = "created_at"

    year = django_filters.ChoiceFilter(
        choices=[], method="filter_year", label="Year",
    )
    date_gte = django_filters.DateFilter(method="filter_date_gte", label="Date")
    date_lte = django_filters.DateFilter(method="filter_date_lte", label="Date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.form.fields.get("year")
        if field is not None:
            # No empty entry of our own: ChoiceField adds one from empty_label,
            # and prepending a second leaves the dropdown with two blank rows.
            source = self.queryset
            if source is None:
                source = self._meta.model._default_manager.all()
            field.choices = year_choices(source, self.date_field)
            field.label = t("filter_year", "Year")

    def _lookup(self, suffix):
        """DateTimeFields need ``__date`` before the comparison, dates do not."""
        model_field = self._meta.model._meta.get_field(self.date_field.split("__")[0])
        prefix = (
            f"{self.date_field}__date"
            if isinstance(model_field, DateTimeField)
            else self.date_field
        )
        return f"{prefix}__{suffix}"

    def filter_year(self, queryset, name, value):
        # `__year` reads the same on a DateField and a DateTimeField, so this
        # needs none of `_lookup`'s branching.
        if not value:
            return queryset
        return queryset.filter(**{f"{self.date_field}__year": value})

    def filter_date_gte(self, queryset, name, value):
        return queryset.filter(**{self._lookup("gte"): value}) if value else queryset

    def filter_date_lte(self, queryset, name, value):
        return queryset.filter(**{self._lookup("lte"): value}) if value else queryset
