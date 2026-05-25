# Local Git forge decision

A separate local GitHub/Forgejo layer is unnecessary for lattice history right now.

The canonical source repository already provides Git history and PR review. Every merged source change can be deterministically centered into a lattice and mapped to atom-level changes:

```text
main repo commit -> centaurize -> lattice snapshot -> atom delta
PR diff         -> deterministic atom/lattice comparison
```

Machine-scale candidate artifacts can live in run directories or object storage until promoted. Human-reviewed accepted changes should enter the main repo as normal PRs.
