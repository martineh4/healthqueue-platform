#!/usr/bin/env bash
# Render a `tofu show` / `tofu plan` text file as Markdown for a PR comment, issue, or job
# summary. Redacts the subscription and tenant IDs (resource IDs embed them and this is a
# public repository) and truncates to stay under GitHub's 65,536-character comment limit.
#
# Usage: plan-comment.sh PLAN_FILE EXIT_CODE COMMIT_SHA [TITLE]
# Env:   SUB_ID, TENANT_ID (optional; redacted when set)
set -euo pipefail

plan_file=$1
exit_code=$2
sha=$3
title=${4:-OpenTofu plan for prod}
max_chars=60000

redacted=$(cat "$plan_file")
[ -n "${SUB_ID:-}" ] && redacted=${redacted//"$SUB_ID"/<subscription-id>}
[ -n "${TENANT_ID:-}" ] && redacted=${redacted//"$TENANT_ID"/<tenant-id>}

if [ "$exit_code" = 0 ]; then
  summary=$(grep -E '^(Plan:|No changes\.)' <<<"$redacted" | head -n1 || true)
  status=":white_check_mark: ${summary:-Plan succeeded}"
else
  status=":x: Plan failed (exit code $exit_code)"
fi

if [ "${#redacted}" -gt "$max_chars" ]; then
  redacted="${redacted:0:$max_chars}"$'\n\n... truncated; see the workflow run for the full output.'
fi

cat <<MD
<!-- tofu-plan -->
### ${title}

${status}

Commit \`${sha:0:7}\` · [workflow run](${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-})

<details><summary>Show plan</summary>

\`\`\`hcl
${redacted}
\`\`\`

</details>
MD
