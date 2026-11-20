"""Select managed state consumers lazily, without importing any checkout code."""

import os

if os.environ.get("STRATA_MANAGED_SOURCE"):
    from strata_managed_state import install_consumer

    install_consumer()

    if os.environ.get("STRATA_ACQUISITION_BOOTSTRAP"):
        from strata_managed_state import install_acquisition

        install_acquisition()
