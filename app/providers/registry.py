"""Provider adapter registry."""

from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping

from app.providers.adapters.bls_international import BLSInternationalProvider
from app.providers.adapters.tlscontact import TLScontactProvider
from app.providers.adapters.vfs_global import VFSGlobalProvider
from app.providers.base import BaseProvider
from app.providers.errors import ProviderNotRegisteredError


class ProviderRegistry:
    """Immutable lookup of provider-specific adapters by stable provider code."""

    def __init__(self, providers: Iterable[BaseProvider]) -> None:
        registered: dict[str, BaseProvider] = {}
        for provider in providers:
            if not provider.provider_code or provider.provider_code in registered:
                raise ValueError(
                    f"Duplicate or empty provider code: {provider.provider_code!r}"
                )
            registered[provider.provider_code] = provider
        self._providers: Mapping[str, BaseProvider] = MappingProxyType(registered)

    def get(self, provider_code: str) -> BaseProvider:
        """Return a registered adapter or raise an explicit configuration error."""
        try:
            return self._providers[provider_code]
        except KeyError as error:
            raise ProviderNotRegisteredError(
                f"No adapter registered for provider {provider_code!r}"
            ) from error

    def provider_codes(self) -> tuple[str, ...]:
        """Return registered provider codes in stable registration order."""
        return tuple(self._providers)


def create_default_registry() -> ProviderRegistry:
    """Create the initial manual-only VFS, BLS, and TLScontact registry."""
    return ProviderRegistry(
        (
            VFSGlobalProvider(),
            BLSInternationalProvider(),
            TLScontactProvider(),
        )
    )
