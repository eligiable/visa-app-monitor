"""Manual-only VFS Global adapter placeholder."""

from app.providers.adapters.manual_check import ManualCheckProvider


class VFSGlobalProvider(ManualCheckProvider):
    """VFS Global placeholder; no portal requests or scraping are performed."""

    def __init__(self) -> None:
        super().__init__("vfs_global")
