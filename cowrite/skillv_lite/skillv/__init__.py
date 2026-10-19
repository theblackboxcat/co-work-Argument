# -*- coding: utf-8 -*-
"""Skill-V-lite for cowrite speak/silence decisions.

Port of the operational idea in Ma et al., Skill-V (arXiv:2610.11781):
versioned falsifiable contracts, an applicability filter, boundary revision
when the rubric disagrees with the outcome, and a non-regression evidence
gate. This package does not add system-prompt clauses and does not speak
to co-address claims.
"""

from skillv.runtime import enabled, maybe_apply

__all__ = ['enabled', 'maybe_apply']
