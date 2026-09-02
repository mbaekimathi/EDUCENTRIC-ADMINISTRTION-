"""Bulk database helpers that preserve update_or_create semantics without N queries."""

from __future__ import annotations

from django.utils import timezone


def bulk_upsert_by_keys(
    model,
    *,
    scope_filter,
    rows,
    key_fields,
    update_fields,
    create_defaults=None,
    batch_size=500,
):
    """
    Upsert rows within a queryset scope using bulk_create and bulk_update.

    ``scope_filter`` limits which existing rows are loaded (e.g. generation or session).
    ``rows`` are dicts containing key fields plus values to create or update.
    ``create_defaults`` are merged into each new row (parent FK ids, etc.).
    """
    if not rows:
        return

    create_defaults = create_defaults or {}
    existing_map = {}
    for obj in model.objects.filter(**scope_filter):
        key = tuple(getattr(obj, field) for field in key_fields)
        existing_map[key] = obj

    to_create = []
    to_update = []
    now = timezone.now()
    stamp_updated_at = "updated_at" in {field.name for field in model._meta.fields}

    for row in rows:
        key = tuple(row[field] for field in key_fields)
        existing = existing_map.get(key)
        if existing is None:
            create_kwargs = {**create_defaults, **row}
            if stamp_updated_at and "updated_at" not in create_kwargs:
                create_kwargs["updated_at"] = now
            to_create.append(model(**create_kwargs))
            continue

        changed = False
        for field in update_fields:
            if field == "updated_at":
                continue
            value = row.get(field)
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            if stamp_updated_at:
                existing.updated_at = now
            to_update.append(existing)

    if to_create:
        model.objects.bulk_create(to_create, batch_size=batch_size)
    if to_update:
        fields = list(update_fields)
        if stamp_updated_at and "updated_at" not in fields:
            fields.append("updated_at")
        model.objects.bulk_update(to_update, fields, batch_size=batch_size)
