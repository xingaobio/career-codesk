"""Shared, deliberately small domain mechanics for the synthetic prototype."""

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from django.db import models


class DomainInvariantError(ValueError):
    """Raised when an application service would violate a product invariant."""


class ImmutableRecordError(DomainInvariantError):
    """Raised when immutable evidence is changed or removed."""


class GuardedQuerySet(models.QuerySet):
    """Do not permit queryset mutation for append-only evidence."""

    def update(self, **kwargs):
        raise ImmutableRecordError("Append-only evidence cannot be updated")

    def delete(self):
        raise ImmutableRecordError("Append-only evidence cannot be deleted")


class AppendOnlyManager(models.Manager.from_queryset(GuardedQuerySet)):
    pass


class StableIdQuerySet(models.QuerySet):
    """Domain identifiers are assigned once and cannot be bulk-rewritten."""

    def update(self, **kwargs):
        if "id" in kwargs:
            raise DomainInvariantError("Stable domain identifiers cannot be changed")
        return super().update(**kwargs)


class StableIdManager(models.Manager.from_queryset(StableIdQuerySet)):
    pass


class StateProjectionQuerySet(models.QuerySet):
    """Projection state changes must go through their domain service."""

    def update(self, **kwargs):
        if "id" in kwargs:
            raise DomainInvariantError("Stable domain identifiers cannot be changed")
        if "state" in kwargs:
            raise DomainInvariantError(
                "Projection state must be changed through its workflow service"
            )
        return super().update(**kwargs)


class StateProjectionManager(models.Manager.from_queryset(StateProjectionQuerySet)):
    pass


_projection_state_change_authorized = ContextVar(
    "projection_state_change_authorized", default=False
)


@contextmanager
def _authorize_projection_state_change():
    """Permit one projection update from a transactional domain service.

    This deliberately private capability replaces model-level mutators.  A caller
    cannot enable a state change merely by setting an attribute on a model instance.
    """
    token = _projection_state_change_authorized.set(True)
    try:
        yield
    finally:
        _projection_state_change_authorized.reset(token)


def projection_state_change_is_authorized() -> bool:
    """Return whether the current service scope may update a projection state."""
    return _projection_state_change_authorized.get()


def domain_id() -> str:
    """Return a stable, non-sequential domain identifier."""
    return uuid4().hex


class DomainRecord(models.Model):
    """Common identity and scope fields for every persisted prototype record."""

    id = models.CharField(primary_key=True, default=domain_id, editable=False, max_length=32)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    schema_version = models.CharField(default="1.0", max_length=32)
    fixture_scope = models.CharField(default="synthetic-demo-v1", max_length=64)
    objects = StableIdManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original_id = type(self).objects.filter(pk=self.pk).values_list("id", flat=True).first()
            if original_id is None:
                raise DomainInvariantError("Stable domain identifiers cannot be reassigned")
        return super().save(*args, **kwargs)


class AppendOnlyRecord(DomainRecord):
    """Evidence that may be created but never revised or erased."""

    objects = AppendOnlyManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Append-only evidence cannot be updated")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Append-only evidence cannot be deleted")
