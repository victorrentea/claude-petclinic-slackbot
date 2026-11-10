#!/bin/zsh
# Ruleset on victorrentea/petclinic main: only repo admins (Victor) may update it.
# Santa Claude's GitHub App is NOT a bypass actor. GitHub Actions can't be one either on a personal
# repo (422 "must be part of the ruleset source or owner organization"), so CI's auto-commit of
# regenerated artifacts on main now fails: regenerate locally before pushing main (Victor's choice, 9 Nov 2026).
gh api -X POST repos/victorrentea/petclinic/rulesets --jq '"ruleset " + (.id|tostring) + " created"' --input - <<'JSON'
{
  "name": "main: only Victor pushes (not Santa Claude)",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}],
  "bypass_actors": [
    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
  ]
}
JSON
