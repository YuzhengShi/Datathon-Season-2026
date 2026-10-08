"""Source adapters, looked up by the ``parser`` name in ``sources.yaml``."""

from __future__ import annotations

from navigator.ingestion.adapters.base import Adapter


def registry() -> dict[str, Adapter]:
    from navigator.ingestion.adapters.curated import CuratedAdapter, CuratedChannelAdapter
    from navigator.ingestion.adapters.isc_index import IscIndexAdapter
    from navigator.ingestion.adapters.policy import ContextOnlyAdapter, PolicyAdapter
    from navigator.ingestion.adapters.sectioned import ListingDetailAdapter, SectionedAwardsAdapter

    adapters: list[Adapter] = [
        IscIndexAdapter(),
        PolicyAdapter(),
        ContextOnlyAdapter(),
        SectionedAwardsAdapter(),
        ListingDetailAdapter(),
        CuratedAdapter(),
        CuratedChannelAdapter(),
    ]
    return {a.name: a for a in adapters}
