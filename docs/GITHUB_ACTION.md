# AgentProof GitHub Action

The composite Action verifies that a checked-out repository still matches a canonical
AgentProof receipt before it asks HREVN to seal that receipt. A successful run produces:

- A signed EB1 Evidence Bundle anchored on Ethereum Sepolia.
- The canonical receipt, EB1 ZIP, clean `.sha256` sidecar, and machine-readable result
  as a GitHub workflow artifact.
- One idempotent pull request comment with the bundle, verification, download, artifact,
  and Etherscan links.

The Action never accepts an API credential as a command-line argument. GitHub and HREVN
tokens exist only in masked environment variables and are not written into the receipt,
bundle, result, comment, or workflow artifact.

## Prepare the receipt

Capture the Codex session locally and commit its canonical receipt with the pull request:

```bash
hrevn-agentproof run \
  --repo . \
  --output .agentproof/agent-session.json \
  --model gpt-5.6-sol \
  "Implement the requested change and run the tests"
```

Only privacy-preserving commitments and repository-relative paths enter the receipt.
Prompts, source code, command text, command output, and diff content remain local.

## Add the repository secret

Create the Actions secret `HREVN_AGENTPROOF_API_KEY` with a credential issued for the
EB1 API. Do not store it in a workflow file, repository variable, receipt, or local
`.env` committed to Git.

## Example workflow

The example uses the public AgentProof `v1` release. Pin it to a full commit SHA in
security-sensitive repositories.

```yaml
name: AgentProof

on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - ".agentproof/agent-session.json"

permissions:
  contents: read
  pull-requests: write

jobs:
  verify-and-seal:
    # Secrets are intentionally unavailable to pull requests from forks.
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
      - uses: miguel-herrero-systems/HREVN-AgentProof@v1
        with:
          receipt-path: .agentproof/agent-session.json
          api-key: ${{ secrets.HREVN_AGENTPROOF_API_KEY }}
          github-token: ${{ github.token }}
```

Pin the Action to a full commit SHA in security-sensitive repositories. The path filter
also avoids resealing unrelated updates and spending Sepolia funds unnecessarily.
If `github-token` is omitted, sealing and artifact upload still complete and the Action
emits a clear warning instead of failing during the optional comment step.

## Fork pull requests

Never use `pull_request_target` to check out and execute untrusted fork code with the
HREVN secret. The example skips sealing for forks. Maintainers can review a fork, bring
the commit onto a trusted branch, and then run AgentProof there.

Repository comparison itself remains available without any credential:

```bash
hrevn-agentproof verify-repo \
  --receipt .agentproof/agent-session.json \
  --repo .
```

## Failure behavior

The Action stops before contacting the EB1 API when the receipt is noncanonical, its
event hash chain is invalid, or a committed repository file is modified or missing.
By default it also rejects output that is not both Ed25519-signed and anchored. The
`allow-pending` input exists only for intentional local/test environments.
