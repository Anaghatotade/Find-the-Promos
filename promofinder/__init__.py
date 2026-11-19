"""PromoFinder: find 20-60s promo moments in timestamped microdrama screenplays."""
__version__ = "1.2.5"

import os as _os

# One maths thread by default (v1.2.5). Hosted CPUs are often a small slice of a large machine
# (Render free: 0.1 CPU); BLAS/OpenMP size their thread pools from the *visible* cores and then
# compete for that slice. Measured: 16 threads on 2 cores cost +78% CPU-seconds for identical results.
# Must run before numpy/scipy/sklearn are imported; an explicit environment setting still wins.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")
