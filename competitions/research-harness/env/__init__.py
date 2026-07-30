"""research_harness environment (REFEREE-SIDE ONLY).

None of this ships in the player image: the world generator, the retrieval index, the
frozen-model client, and the scoring rules all live in the referee. The player sandbox
holds the miner's harness and nothing else.

Import from the submodules directly (`from env.world import generate_world`) — there are no
re-exports here, so nothing can drift out of sync with what the modules actually define.
"""
