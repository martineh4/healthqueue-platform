#!/usr/bin/env bash
# Render a `tofu show` / `tofu plan` text file as Markdown for a PR comment, issue, or job
# summary. Redacts every GUID (resource IDs embed the subscription, and this is a public
# repository) and truncates to stay under GitHub's 65,536-character comment limit.
#
# Usage: plan-comment.sh PLAN_FILE EXIT_CODE COMMIT_SHA [TITLE]
# Env:   SUB_ID, TENANT_ID (optional; redacted when set)
set -euo pipefail

plan_file=$1
exit_code=$2
sha=$3
title=${4:-OpenTofu plan for prod}
max_chars=60000

# Named replacements first (clearer output), then any remaining GUID as a backstop: a
# malformed secret (e.g. a byte-order mark from Windows PowerShell piping) once defeated an
# exact-match redaction, and object/principal IDs are no business of a public comment.
guid='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
redacted=$(cat "$plan_file")
for pair in "${SUB_ID:-}=<subscription-id>" "${TENANT_ID:-}=<tenant-id>"; do
  id=$(grep -oE "$guid" <<<"${pair%%=*}" || true)
  [ -n "$id" ] && redacted=${redacted//"$id"/${pair#*=}}
done
redacted=$(sed -E "s/$guid/<guid>/g" <<<"$redacted")

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
