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
- FMU/modelDescription.xml parsing of untrusted archive payloads
- accidental inclusion of private examples, credentials, customer data, or
  product infrastructure details

The package does not execute model code. Applications that execute compiled
plans are responsible for sandboxing, connector authentication, and runtime
authorization.

## FMU And XML Handling

TwinGraph can parse an FMU archive's `modelDescription.xml` to derive a
data-only IO contract. The package never executes FMU binaries.

Applications accepting user-supplied FMUs should still treat `.fmu` files as
untrusted zip archives:

- reject oversized files and enforce decompressed-size limits before parsing
- parse FMUs in the application security boundary for multi-tenant services
- never execute FMU binaries from the TwinGraph OSS core
- use a hardened XML parser in the application layer if parsing arbitrary
  tenant uploads

The stdlib parser path rejects XML `DOCTYPE` and `ENTITY` declarations before
parsing to block entity-expansion and external-entity constructs without adding
a runtime dependency.
