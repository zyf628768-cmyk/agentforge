# Durable model budgets

Real inference requires an explicit persistent account. Free local inference costs
zero provider dollars but still consumes a shared request/token budget. Recorded
offline fixtures remain separate.

```sh
agentforge --home .agentforge budget create local-development --usd 0 --tokens 500000 --requests 10
agentforge --home .agentforge budget status local-development
agentforge --home .agentforge budget history local-development
```

Clients using the same home/account share immutable lifetime caps in SQLite under
`HOME/billing`. A `BEGIN IMMEDIATE` reservation is FULL-synchronously committed
before transport. Hard process exit leaves it charged/held; restarting cannot reset
it. Failed/unknown calls still count as requests. Unknown reservations never expire
or refund automatically. Money uses integer nano-dollars rounded upward.

Completed valid usage settles to actual cost/tokens. Unexpected usage keeps its
hold until explicit operator reconciliation:

```sh
agentforge budget reconcile RESERVATION_ID --usd 0.012 --tokens 1200 --receipt reviewed-provider-receipt.json --note "Reviewed actual usage"
```

The journal stores prior hold, actual usage, receipt SHA-256 and a redacted note;
it does not store raw provider receipts or credentials. Reconciliation is a trusted
operator decision, not automatic authentication of provider evidence. An overage
can make remaining budget negative; subsequent requests are blocked. Only an
unresolved reservation can be reconciled once. Limits cannot silently increase.

Use the same account/home for calls sharing a ceiling. Selecting another scope is
a separate operator decision; this is not a provider account-wide cap or protection
against an owner who edits the DB. Back up the private billing directory with
clients stopped. Foreign, corrupt, future-schema or inaccessible ledgers refuse
real inference. Tests include eight concurrent processes and hard process exit,
without any paid call or real key.
