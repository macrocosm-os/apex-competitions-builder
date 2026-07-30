"""Baseline data-loading override: NO change from upstream nanochat.

Re-exports nanochat's own BOS-aligned best-fit packing dataloader unmodified (see
PROVENANCE.md). A miner competing on data packing/loading replaces this file's contents
in EXTRA_FILES["data.py"] with their own generator matching the same signature.
"""

from __future__ import annotations

from nanochat.dataloader import tokenizing_distributed_data_loader_with_state_bos_bestfit as data_iterator

__all__ = ["data_iterator"]
