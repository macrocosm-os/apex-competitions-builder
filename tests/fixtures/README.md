# Test fixtures

`solo/` is a complete, valid `apex.competition.v1` solo spec used to test the loader end to end
(schema validation, `input_schema` `$ref` resolution, resource ceilings, CLI arg handling).

It is a **test fixture, not an example to copy.** The worked example competition lives in its own
repo: https://github.com/macrocosm-os/apex-competition-hello-world — that is what designers should
read and fork, and it demonstrates the vendored-gym_v1 image pattern this repo's fixtures don't.
