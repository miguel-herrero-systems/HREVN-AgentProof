# AgentProof sample receipt

This directory lets judges exercise repository re-verification without running Codex or rebuilding the production demo.

- `agent-session.json` is the canonical, privacy-preserving session document sealed in live bundle `BND-A461FE81F6B2`.
- `demo-repository/calculator.py` reproduces the final file commitment in that receipt.
- `demo-repository/README.txt` explains the browser demo variant.

From the repository root, after installing the Python package:

```bash
hrevn-agentproof verify-repo \
  --receipt examples/agent-session.json \
  --repo examples/demo-repository
```

Expected result: `MATCH` with SHA-256 `0049214146c09e015865e54237ecc4d15c9e043886cb20d1d9c68659bf744bc9` for `calculator.py`.

For the red case, change `left + right` to `left - right` and repeat the command. AgentProof reports `MISMATCH` for `calculator.py`. The sample receipt contains hashes and metadata, not command text, source code, command output, prompts, or diffs.

The corresponding EB1 root is signed with Ed25519 and anchored on Sepolia in [transaction `0x19a05ed3...d7308f3`](https://sepolia.etherscan.io/tx/0x19a05ed31231e67388cda6513d18d72e5bafa38b1b6634fc772da6ba9d7308f3).
