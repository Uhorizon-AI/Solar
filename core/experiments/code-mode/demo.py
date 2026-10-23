"""Reproducible direct-call versus Code Mode comparison; no model calls."""
import json
from server import execute, invoke, search

CODE = """const customer = await solar.getCustomer({customerId: 123});
const invoices = await solar.getInvoices({customerId: customer.id});
const pending = invoices.filter(invoice => invoice.status === "pending");
return {customer: customer.name, pendingCount: pending.length,
        totalCents: pending.reduce((sum, invoice) => sum + invoice.amountCents, 0)};"""


def demo():
    catalog = search({"query": "customer invoice"})
    customer = invoke("getCustomer", {"customerId": 123})
    invoices = invoke("getInvoices", {"customerId": customer["id"]})
    expected = {"customer": customer["name"], "pendingCount": 20,
                "totalCents": sum(row["amountCents"] for row in invoices if row["status"] == "pending")}
    execution = execute({"code": CODE})
    assert execution.get("result") == expected, execution
    size = lambda value: len(json.dumps(value, separators=(",", ":")).encode())
    return {"search": catalog, "code": CODE, "execution": execution,
            "comparison": {"direct_data_response_bytes": size([customer, invoices]),
                           "code_mode_response_bytes_including_trace": size(execution),
                           "backend_calls_in_both": 2,
                           "direct_execution_tool_calls": 2,
                           "code_mode_execution_tool_calls": 1,
                           "discovery_excluded_equally": True,
                           "measured_model_tokens_or_latency": False}}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2))
