"""Run the intake/approval workflow against a running local API."""
import argparse
import json
import uuid

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--text", help="Natural-language source; requires the API to use Ollama.")
parser.add_argument("--approve", action="store_true", help="Explicitly approve and create the demo order.")
args = parser.parse_args()
source = args.text or json.dumps({
    "customer": "Acme Demo", "order_date": "2026-11-19T10:00:00Z",
    "lines": [{"sku": "SKU-001", "quantity": 2, "price": "10.50"}],
})
with httpx.Client(base_url=args.url, timeout=100) as client:
    def post(path, **kwargs):
        response = client.post(path, **kwargs)
        if response.is_error:
            raise SystemExit(f"HTTP {response.status_code}: {response.text}")
        return response.json()

    run = post("/agent/runs", json={"request_id": f"demo-{uuid.uuid4()}", "text": source})
    print(json.dumps(run, indent=2, ensure_ascii=False))
    if args.approve and run["status"] == "awaiting_approval":
        post(f"/agent/runs/{run['id']}/decision", json={"version": run["version"], "decision": "approve"})
        result = post(f"/agent/runs/{run['id']}/execute")
        replay = post(f"/agent/runs/{run['id']}/execute")
        assert result["order_id"] == replay["order_id"]
        print(f"Pedido creado: {result['order_id']}. Reintento: mismo pedido, sin duplicación.")
    else:
        print("No se creó ningún pedido. Revisá el borrador y sus datos pendientes en /docs.")
