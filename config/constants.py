"""Single source of truth for the model's physical and economic constants.

Nothing in `models/` or `pipelines/` may hardcode these values — import them
from here, so that a sensitivity run or a revised assumption changes exactly
one file. Every constant below states its derivation and whether it is
sourced or merely an industry-typical planning figure.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Delivered power per accelerator-hour
# --------------------------------------------------------------------------
# Derivation of the 1.10 kW default (project brief, Phase 3):
#
#   (ACCELERATOR_TDP_KW + IT_OVERHEAD_KW) * PUE
#   = (0.700 + 0.180) * 1.25
#   = 1.100 kW per accelerator-hour
#
# The 700 W accelerator TDP is a nameplate figure for a current-generation
# datacentre accelerator. PUE 1.25 is an industry-typical planning figure,
# NOT a measurement — operator-reported PUE is self-reported and unaudited
# (see paper/main.tex, Limitations). IT_OVERHEAD_KW is the CPU/NIC/storage
# share attributable to one accelerator, at the IT load level (i.e. before
# the PUE multiplier is applied).
#
# None of these three inputs is independently sourced per-site; they are the
# project's stated defaults. Treat conclusions that are sensitive to them as
# weak, and read the sensitivity sweep in paper/main.tex Section 7.

ACCELERATOR_TDP_KW: Final[float] = 0.700
IT_OVERHEAD_KW: Final[float] = 0.180
PUE: Final[float] = 1.25

#: Delivered kW drawn from the grid per accelerator-hour, PUE included.
#: THE single named constant referred to in the project brief.
DELIVERED_KW: Final[float] = (ACCELERATOR_TDP_KW + IT_OVERHEAD_KW) * PUE

#: Inclusive bounds for the delivered_kW sensitivity sweep (project brief).
DELIVERED_KW_SENSITIVITY_MIN: Final[float] = 0.90
DELIVERED_KW_SENSITIVITY_MAX: Final[float] = 1.40

#: Bounds for the PUE sensitivity sweep. 1.10 is about as good as a
#: hyperscale facility credibly claims; 1.60 is typical of older or
#: hot-climate colocation. Both are planning bounds for a sweep, not
#: measurements of any specific site.
PUE_SENSITIVITY_MIN: Final[float] = 1.10
PUE_SENSITIVITY_MAX: Final[float] = 1.60


# --------------------------------------------------------------------------
# Non-power marginal operating expense
# --------------------------------------------------------------------------
# The project brief is explicit: parameterise opex, do NOT invent a point
# estimate. Accordingly there is deliberately no default value here.
#
# Non-power marginal opex (staffing, bandwidth, maintenance) per GPU-hour
# must be passed explicitly into models.spark_spread.shutdown_price(), and
# reported as a range. No public source for it has been identified yet —
# tracked in GitHub issue #14. Until one is, any headroom figure this
# project publishes is conditional on an assumed opex, and must be labelled
# as such in the paper.

MARGINAL_OPEX_USD_PER_GPU_HOUR: Final[None] = None


# --------------------------------------------------------------------------
# Unit conversions
# --------------------------------------------------------------------------
KWH_PER_MWH: Final[float] = 1000.0
