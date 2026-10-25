#!/usr/bin/env bash
# Apply GitHub security settings to a parabyte-ca repository. Run on your workstation with the gh CLI
# signed in as the repo owner (gh auth login). Idempotent: safe to re-run.
#
#   ./github-harden.sh parabyte-ca/karoulette            show current settings, change nothing
#   ./github-harden.sh parabyte-ca/karoulette --apply    apply
#
# Rollback: Settings > Rules > Rulesets > "main protection" > Delete; the other settings are toggles in
# Settings > Code security and Settings > Actions > General.
set -euo pipefail

REPO="${1:?usage: $0 owner/repo [--apply]}"
APPLY="${2:-}"
command -v gh >/dev/null || { echo "gh CLI is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

echo "== Current state of $REPO"
gh api "repos/$REPO" --jq '{visibility, default_branch, has_wiki, has_projects, allow_forking,
  security_and_analysis}'
gh api "repos/$REPO/actions/permissions/workflow" --jq '{default_workflow_permissions, can_approve_pull_request_reviews}'
echo "Rulesets:"; gh api "repos/$REPO/rulesets" --jq '.[] | "  \(.id) \(.name) (\(.enforcement))"'
echo "Deploy keys:"; gh api "repos/$REPO/keys" --jq '.[] | "  \(.id) \(.title) read_only=\(.read_only) created=\(.created_at)"'
echo "Webhooks:"; gh api "repos/$REPO/hooks" --jq '.[] | "  \(.id) \(.config.url) active=\(.active)"'
echo "Collaborators:"; gh api "repos/$REPO/collaborators" --jq '.[] | "  \(.login) \(.role_name)"'
echo "Dependabot alerts (open):"; gh api "repos/$REPO/dependabot/alerts?state=open" --jq 'length' 2>/dev/null || echo "  (alerts disabled)"
echo "Secret scanning alerts (open):"; gh api "repos/$REPO/secret-scanning/alerts?state=open" --jq 'length' 2>/dev/null || echo "  (secret scanning disabled)"

[[ "$APPLY" == "--apply" ]] || { echo; echo "Dry run. Re-run with --apply to change settings."; exit 0; }

echo "== Applying"
# Dependabot alerts and security update PRs
gh api -X PUT "repos/$REPO/vulnerability-alerts" >/dev/null
gh api -X PUT "repos/$REPO/automated-security-fixes" >/dev/null
# Secret scanning and push protection (free on public repositories)
gh api -X PATCH "repos/$REPO" --input - >/dev/null <<'JSON'
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
                           "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
# Private vulnerability reporting (the channel SECURITY.md points to)
gh api -X PUT "repos/$REPO/private-vulnerability-reporting" >/dev/null || echo "  private vulnerability reporting: enable in Settings > Code security"
# GITHUB_TOKEN read-only by default; workflows ask for more per job
gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false >/dev/null

# Branch ruleset on the default branch: PRs only, CI must pass, no force pushes or deletion.
# Required signatures is left out on purpose: commits pushed from tools that don't sign would block merges.
# Turn it on (add {"type": "required_signatures"}) once you sign commits and squash-merge from GitHub.
if ! gh api "repos/$REPO/rulesets" --jq '.[].name' | grep -qx "main protection"; then
  gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null <<'JSON'
{
  "name": "main protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "test"}, {"context": "e2e"}, {"context": "load"}, {"context": "docker"}]}}
  ]
}
JSON
  echo "  created ruleset \"main protection\""
else
  echo "  ruleset \"main protection\" already exists (edit it in Settings > Rules)"
fi
echo "Done. After the Security workflow has run once, add its job names (gitleaks (full history), etc.)"
echo "to the ruleset's required checks."
