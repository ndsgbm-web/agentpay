#!/usr/bin/env bash
# Recompile all Solidity contracts.
# Output: build/*.bin and contracts/*abi.json (dict with "abi" and "bytecode")
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
mkdir -p "$BUILD"

SOLCJS="${SOLCJS:-/tmp/node_modules/.bin/solcjs}"

# main contracts
"$SOLCJS" --bin --abi --optimize \
    "$ROOT/contracts/AgentPayEscrow.sol" \
    "$ROOT/contracts/AgentPayVault.sol" \
    "$ROOT/contracts/MockUSDC.sol" \
    -o "$BUILD"

# mocks
"$SOLCJS" --bin --abi --optimize \
    "$ROOT/contracts/mocks/MockAave.sol" \
    -o "$BUILD"

# generate .abi.json dicts (with bytecode embedded) for deploy.py / e2e.py
python3 - "$BUILD" "$ROOT" <<'PY'
import json, re, sys
build, root = sys.argv[1], sys.argv[2]
import pathlib
def strip(s): return re.sub(r'^_+', '', s.strip())
mapping = {
    f"{build}/contracts_AgentPayEscrow_sol_AgentPayEscrow.bin": f"{root}/contracts/AgentPayEscrow.abi.json",
    f"{build}/contracts_AgentPayEscrow_sol_AgentPayEscrow.abi": None,
    f"{build}/contracts_AgentPayVault_sol_AgentPayVault.bin":    f"{root}/contracts/AgentPayVault.abi.json",
    f"{build}/contracts_AgentPayVault_sol_AgentPayVault.abi":    None,
    f"{build}/contracts_MockUSDC_sol_MockUSDC.bin":              f"{root}/contracts/MockUSDC.abi.json",
    f"{build}/contracts_MockUSDC_sol_MockUSDC.abi":              None,
    f"{build}/contracts_mocks_MockAave_sol_MockAave.bin":        f"{root}/contracts/mocks/MockAave.abi.json",
    f"{build}/contracts_mocks_MockAave_sol_MockAave.abi":        None,
}
# we need to associate each .bin with its .abi — use the matching name
pairs = [
    ("AgentPayEscrow", f"{root}/contracts/AgentPayEscrow.abi.json", f"{build}/contracts_AgentPayEscrow_sol_AgentPayEscrow"),
    ("AgentPayVault",  f"{root}/contracts/AgentPayVault.abi.json",  f"{build}/contracts_AgentPayVault_sol_AgentPayVault"),
    ("MockUSDC",       f"{root}/contracts/MockUSDC.abi.json",       f"{build}/contracts_MockUSDC_sol_MockUSDC"),
    ("MockAave",       f"{root}/contracts/mocks/MockAave.abi.json", f"{build}/contracts_mocks_MockAave_sol_MockAave"),
]
for name, dst, base in pairs:
    abi  = json.load(open(base + ".abi"))
    bin_ = strip(open(base + ".bin").read())
    json.dump({"abi": abi, "bytecode": bin_}, open(dst, "w"), indent=2)
    print(f"wrote {dst}  ({len(bin_)} chars bytecode)")

# stage friendly-named copies in build/
for name in ["AgentPayEscrow", "AgentPayVault", "MockUSDC", "MockAave"]:
    if name == "MockAave":
        src = f"{build}/contracts_mocks_MockAave_sol_MockAave"
    else:
        src = f"{build}/contracts_{name}_sol_{name}"
    if pathlib.Path(src + ".bin").exists():
        open(f"{build}/{name}.bin", "w").write(strip(open(src + ".bin").read()))
    if pathlib.Path(src + ".abi").exists():
        open(f"{build}/{name}.abi", "w").write(open(src + ".abi").read())
PY
echo "build done"
