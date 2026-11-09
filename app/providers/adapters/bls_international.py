"""Manual-only BLS International adapter placeholder."""

from app.providers.adapters.manual_check import ManualCheckProvider


class BLSInternationalProvider(ManualCheckProvider):
    """BLS placeholder; no portal requests or scraping are performed."""

    def __init__(self) -> None:
        super().__init__("bls_international")
