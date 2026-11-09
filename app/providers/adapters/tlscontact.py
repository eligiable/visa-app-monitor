"""Manual-only TLScontact adapter placeholder."""

from app.providers.adapters.manual_check import ManualCheckProvider


class TLScontactProvider(ManualCheckProvider):
    """TLScontact placeholder; no portal requests or scraping are performed."""

    def __init__(self) -> None:
        super().__init__("tlscontact")
