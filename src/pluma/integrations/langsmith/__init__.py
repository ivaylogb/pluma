"""Pluma LangSmith integration.

Converts LangSmith experiments (Dataset-Experiment) and project runs
(production traces) into agent-researcher's failing-eval input. See
README.md for the workflow split and field mapping.
"""

from .runs_to_failing_evals import runs_from_experiment, runs_from_project

__all__ = ["runs_from_experiment", "runs_from_project"]
