# Step 28 — LLM Translation Endpoint

Generates strategy Python source code from a natural-language description, using
the Claude API. Output is run through the same validator used for hand-written
code.

## What This Ships

| File | Status | Purpose |
|------|--------|---------|
| `packages/strategy/llm_translator.py` | NEW | Claude API client + system prompt + tool-use enforcement |
| `services/api/routers/user_strategies.py` | REPLACES Step 27 | Adds `POST /user-strategies/translate` endpoint |
| `apply_step28_patches.py` | NEW (run once) | Patches `pyproject.toml` (adds anthropic dep) + `docker-compose.yml` (adds env var) |

## Apply (Mac)

```bash
cd ~/signal-platform
unzip -o ~/Downloads/step28-llm-translate.zip

# Apply patches to pyproject.toml + docker-compose.yml
python3 apply_step28_patches.py

# Verify the two patches landed
git diff pyproject.toml docker-compose.yml

# Clean up the patch script and commit
rm apply_step28_patches.py
git status
git add -A
git commit -m "Step 28: LLM translation endpoint (NL → strategy Python)"
git push
```

## Deploy (Box)

Two things have to happen on the box:

1. **Export the Anthropic API key** in the shell that runs docker compose:
   ```bash
   echo 'export ANTHROPIC_API_KEY=sk-ant-your-key-here' >> ~/.bashrc
   source ~/.bashrc
   # Verify
   echo "Key set: ${ANTHROPIC_API_KEY:+yes}"
   ```

2. **Rebuild and redeploy** — this will take ~60-90s because pyproject.toml
   changed and the pip install layer needs to re-run:
   ```bash
   cd ~/app
   git pull
   docker compose build api
   docker compose up -d --force-recreate api
   sleep 5
   docker compose logs --tail=20 api | grep -v "/health"
   ```

## Verify

```bash
JWT=$(curl -s -X POST https://cimcha-signal.us.auth0.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "GebwZSFIIUVwcq9zhy2Ev7EBmQ9Pbnyw",
    "client_secret": "LsDhK10Kpg4uM70FcjHv8lFCoAsJnUDiDW9WFaQAqjMSXBs70LNzF5un5hGT5m8Q",
    "audience": "https://signal.cimcha.com/api",
    "grant_type": "client_credentials"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test 1: Translate "RSI mean reversion" — should generate valid code
echo "=== Test 1: RSI mean reversion ==="
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "nl_description": "Buy BTC when RSI (14-period) drops below 30, sell when RSI goes above 70. Use a small position size."
  }' \
  "https://signal.cimcha.com/api/user-strategies/translate" | python3 -m json.tool

# Test 2: Translate "Bollinger Band reversion"
echo ""
echo "=== Test 2: Bollinger reversion (note: BB indicator is NOT in our framework — see how LLM handles) ==="
curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "nl_description": "When ETH price drops 2 standard deviations below its 20-period mean, buy. Close when price returns to the mean."
  }' \
  "https://signal.cimcha.com/api/user-strategies/translate" | python3 -m json.tool

# Test 3: End-to-end — translate, save, run backtest
echo ""
echo "=== Test 3: Translate → save → run backtest ==="
TRANSLATION=$(curl -s -X POST -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"nl_description": "Simple momentum: buy BTC when current close is 5% above its 50-period SMA, sell when below."}' \
  "https://signal.cimcha.com/api/user-strategies/translate")
SOURCE=$(echo "$TRANSLATION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('source_code') or '')")
echo "Translation OK? $(echo $TRANSLATION | python3 -c 'import sys,json; print(json.load(sys.stdin)["ok"])')"

if [ -n "$SOURCE" ]; then
  # Save it
  SAVE_PAYLOAD=$(python3 -c "
import json
src = '''$SOURCE'''
print(json.dumps({
    'name': 'MomentumLLM',
    'description': 'Generated from English description',
    'nl_description': 'Simple momentum: buy BTC when current close is 5% above its 50-period SMA, sell when below.',
    'source_code': src,
}))
")
  echo ""
  echo "Saving the generated strategy:"
  curl -s -X POST -H "Authorization: Bearer $JWT" \
    -H "Content-Type: application/json" \
    -d "$SAVE_PAYLOAD" \
    "https://signal.cimcha.com/api/user-strategies" | python3 -m json.tool
fi
```

## What Test Output Should Look Like

For Test 1 (RSI mean reversion), `ok` should be `true`, with `source_code` containing
a complete Python module that:
- Imports from `packages.strategy.base` and `packages.strategy.context`
- Defines a Pydantic params class (with rsi_period, oversold, overbought thresholds)
- Defines a Strategy subclass with `on_init` and `on_bar`
- Uses `ctx.rsi(self.symbol, period)` and checks for None
- Has buy/sell logic at the thresholds

The `params_schema` field should be populated with a JSON Schema. Cost is logged
at the end: input_tokens + output_tokens (typically 200-400 tokens out).

## Cost Awareness

Each translation costs approximately:
- ~2000-3000 input tokens (the system prompt is large)
- ~400-800 output tokens (the generated code)
- ~$0.005-0.015 per call at current Anthropic pricing

The system prompt is sent every call. We could cache it with prompt caching
later — that's a polish step.

## Known Limitations

- Single-shot generation; refinement is supported via `previous_source` + `feedback`
  but no frontend exposure yet (Step 29)
- LLM may use indicators we don't have (e.g., Bollinger Bands) → validator catches it
  but the user gets a "forbidden_import" or similar error
- No streaming — the whole response is returned at once (5-15s latency)
- The system prompt isn't cached on Anthropic's side yet
