#!/usr/bin/env bash
#
# Regenerate everything under examples/output/ from the example networks.
#
#     ./scripts/run_examples.sh
#
# Every figure quoted in examples/*.md comes from here, so re-running this
# after changing a model or the report format is what keeps the committed
# output honest. tests/test_examples.py fails if the two drift apart.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
    echo "No interpreter at $PYTHON." >&2
    echo "Create one with:  python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    echo "Or point PYTHON at your own:  PYTHON=python3 $0" >&2
    exit 1
fi

for model in examples/*.json; do
    name="$(basename "$model" .json)"
    echo "==> $name"
    "$PYTHON" -m chokepoint analyze "$model" --k 3 --out "examples/output/$name" >/dev/null
done

# One what-if alongside the DMZ report, because that example exists to show a
# single misconfiguration dominating the result and the number only lands if
# you can see the before and after.
echo "==> dmz what-if (remove the legacy rule)"
"$PYTHON" -m chokepoint whatif examples/dmz.json \
    --apply "Remove the legacy DMZ-to-database firewall rule" \
    > examples/output/dmz/whatif-remove-legacy-rule.txt

echo
echo "Done. Regenerated output for $(ls -1 examples/*.json | wc -l | tr -d ' ') networks."
