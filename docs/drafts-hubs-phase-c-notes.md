# Plan 16 — Phase C notes

NA Hub now has nine creation actions plus Send to pillar bot, using the shared
generator and adapter-owned templates. Its name-derived UUID5 identities differ
from Mach Hub; Mach Hub keeps its existing identity. The legacy NA: Mach Hub
artifact is replaced by NA-Hub.draftsAction.

Pillar sends write local subsystem briefs only. Preview and execution go through
the existing mach run → subsystem dispatcher → configured role/router. Secrets
are configured by the user; this phase makes no delivery or network calls.
Linear creates a gated linear-comment brief; profiles propose intel CSV changes.

Tests cover every action, validation parity, mobile outbox, cancellation, failures,
resends, identities, deterministic rebuilds and dispatcher dry runs. Phase D still
needs import/device verification and legacy installed-action cleanup. Confirm real
pillar IDs and research output folders before using the templates.

Validation: `bash tests/run.sh` passed all 13 groups, including upkeep; Python
ran 98 tests with three skips. Node syntax checks passed for both JS sources,
the mock runner and generated scripts. Rebuilding both checked-in actions was
byte-identical; identity tests preserve Mach Hub and distinguish NA Hub.

Git commits are blocked by the worktree metadata being read-only; changes are
left for another committer. No push, publication or live delivery was performed.
