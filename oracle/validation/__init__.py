"""Independent artifact validation for Stage 1 runs.

The validator intentionally consumes only files inside a run directory.  It
does not infer semantic safety from prose, compression ratio, or a successful
restore alone; every gate requires machine-readable evidence.
"""

from .validator import ArtifactValidator, validate_run

__all__ = ["ArtifactValidator", "validate_run"]
