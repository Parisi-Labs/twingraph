# Security Policy

TwinGraph is an intermediate representation package. It should not contain
credentials, customer data, live service endpoints, or proprietary runtime
logic.

## Reporting

Please report security issues privately to the maintainers rather than opening a
public issue with exploit details.

## Scope

Security-sensitive areas include:

- schema or parser behavior that can crash trusted consumers
- unsafe assumptions in canonicalization or hashing
- leakage-safety checks that incorrectly certify horizon-feeding data
- accidental inclusion of private examples, credentials, customer data, or
  product infrastructure details

The package does not execute model code. Applications that execute compiled
plans are responsible for sandboxing, connector authentication, and runtime
authorization.
