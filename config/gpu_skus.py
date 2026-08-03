"""The compute-price basket: accelerator counts per cloud VM SKU.

To express a VM's advertised hourly price as USD per GPU-hour we need to
know how many accelerators that VM contains. Cloud price APIs do not carry
that number, so it is recorded here — each entry carries the public source
it was read from and the date it was verified.

Nothing in this file may be filled in from memory or inference. If a SKU's
accelerator count cannot be read off a citable public page, it does not go
in the basket, and the pipeline emits no USD-per-GPU-hour figure for it.

Source: MicrosoftDocs/azure-compute-docs, the public repository behind
Microsoft Learn's VM size documentation. Chosen over the rendered Learn
pages because it is version-controlled, free, and directly citable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

AZURE_DOCS_REPO: Final[str] = (
    "https://github.com/MicrosoftDocs/azure-compute-docs/blob/main/"
    "articles/virtual-machines/sizes/gpu-accelerated"
)


@dataclass(frozen=True)
class GpuSku:
    """One VM SKU in the price basket, with its sourced accelerator count."""

    provider: str
    segment: str
    """'hyperscaler' or 'neocloud' — reported separately, never blended."""
    arm_sku_name: str
    accelerator_model: str
    accelerator_count: int
    accelerator_memory_gb: int
    source_url: str
    as_of_date: str


#: Azure GPU SKUs whose accelerator counts have been read off the public
#: Microsoft docs and verified on the date below. Extend deliberately: every
#: addition needs its own source_url.
AZURE_GPU_SKUS: Final[tuple[GpuSku, ...]] = (
    GpuSku(
        provider="azure",
        segment="hyperscaler",
        arm_sku_name="Standard_ND96isr_H100_v5",
        accelerator_model="NVIDIA H100",
        accelerator_count=8,
        accelerator_memory_gb=640,
        source_url=f"{AZURE_DOCS_REPO}/ndh100v5-series.md",
        as_of_date="2026-08-03",
    ),
    GpuSku(
        provider="azure",
        segment="hyperscaler",
        arm_sku_name="Standard_NC24ads_A100_v4",
        accelerator_model="NVIDIA A100",
        accelerator_count=1,
        accelerator_memory_gb=80,
        source_url=f"{AZURE_DOCS_REPO}/nca100v4-series.md",
        as_of_date="2026-08-03",
    ),
    GpuSku(
        provider="azure",
        segment="hyperscaler",
        arm_sku_name="Standard_NC48ads_A100_v4",
        accelerator_model="NVIDIA A100",
        accelerator_count=2,
        accelerator_memory_gb=160,
        source_url=f"{AZURE_DOCS_REPO}/nca100v4-series.md",
        as_of_date="2026-08-03",
    ),
    GpuSku(
        provider="azure",
        segment="hyperscaler",
        arm_sku_name="Standard_NC96ads_A100_v4",
        accelerator_model="NVIDIA A100",
        accelerator_count=4,
        accelerator_memory_gb=320,
        source_url=f"{AZURE_DOCS_REPO}/nca100v4-series.md",
        as_of_date="2026-08-03",
    ),
)

#: Azure regions to price. Kept small and explicit rather than "all regions",
#: so the basket composition is a stated choice rather than an artefact of
#: whatever the API happened to return.
AZURE_REGIONS: Final[tuple[str, ...]] = ("eastus", "westeurope", "northeurope")


def sku_by_arm_name(arm_sku_name: str) -> GpuSku | None:
    """Look up a basket entry, or None if the SKU is not in the basket."""
    for sku in AZURE_GPU_SKUS:
        if sku.arm_sku_name == arm_sku_name:
            return sku
    return None
