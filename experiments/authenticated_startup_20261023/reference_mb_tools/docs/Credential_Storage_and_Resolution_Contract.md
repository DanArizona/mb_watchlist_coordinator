# Credential Storage and Resolution Contract

**Status:** Accepted

**Decision date:** 2026-09-19

**Scope:** The `mb_package` repository family and the MasterBot/El-Cheapo
operating environment

**Canonical owner:** `mb_tools`

## 1. Purpose

This document is the authoritative design contract for storing, locating,
loading, and retiring credentials used by `mb_package` applications. It records
security invariants and component responsibilities before additional providers
are integrated.

This is not an operator runbook. User-facing creation, validation, rotation,
and recovery commands belong in the applicable Operations Quick Reference only
after their implementation has been tested.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**
describe normative requirements.

## 2. Decision

1. Programmatic credentials MUST be stored in password-encrypted `.ecfg`
   files supported by `mb_tools.secure_config` unless a provider-controlled
   token store or a later accepted contract defines a stronger mechanism.
2. Each provider MUST have a separate `.ecfg` file. A single aggregate file
   containing unrelated providers' credentials is prohibited.
3. Credential files MUST remain outside source repositories and MUST NOT be
   committed, even though their contents are encrypted.
4. Each machine and process MUST receive only the credentials it needs.
5. Human website-login passwords SHOULD remain in a password manager. They
   MUST NOT be exposed to project software when an API key, application token,
   OAuth flow, or provider-specific machine credential is available.
6. Ordinary configuration and secrets MUST remain separate. Enable flags,
   paths, timeouts, retry limits, and endpoints MAY use the established
   non-secret configuration system. API keys, application secrets, passwords,
   tokens, and encryption keys MUST use the secure credential path.

## 3. Ownership boundary

`mb_tools` owns:

- the `.ecfg` file format and encryption/decryption implementation;
- the encrypted-configuration editor;
- shared path-resolution conventions;
- reusable credential validation and redaction behavior; and
- provider-neutral security requirements in this contract.

Provider-specific applications own:

- the exact credentials they require;
- provider-specific validation beyond basic presence and type checks;
- the decision to fail or disable an optional integration when credentials are
  unavailable; and
- operator documentation after the integration is validated.

No application may silently introduce a second credential-storage convention.
A necessary exception must be documented here or in a superseding contract.

## 4. Storage model

### 4.1 Service-specific files

The default filename is:

```text
secure_<service>.ecfg
```

The file SHOULD reside below the machine's configured `MB_VAULT`. Credential
vaults SHOULD be machine-local. If `MB_VAULT` resolves to shared storage, the
service-specific override MUST select a machine-local credential file unless a
separate security review explicitly approves sharing.

Credential files MUST NOT be copied or synchronized to a machine that does not
need them. In particular, MasterBot and El-Cheapo do not share a credential
vault merely because both participate in the same workflow.

Windows access controls SHOULD restrict each credential file and its containing
directory to the account that operates the relevant process.

### 4.2 Password handling

An `.ecfg` encryption password:

- MUST NOT be stored in the same `.ecfg` file;
- MUST NOT be committed to a repository;
- MUST NOT be placed in a tracked or untracked batch file beside the source;
- MUST NOT be logged; and
- SHOULD be entered interactively once at process startup while processes are
  human-started.

Unattended password bootstrap is not authorized by this contract. A future
requirement for unattended restart must select and document an operating-system
backed mechanism, such as Windows Credential Manager or an equivalent protected
store, before implementation.

## 5. Path-resolution contract

New service integrations MUST resolve an encrypted configuration path in this
order:

1. an explicit command or API argument, where the interface supports one;
2. the service-specific `MB_<SERVICE>_ECFG` environment variable; and
3. `%MB_VAULT%\secure_<service>.ecfg`.

If no candidate is configured or the selected file does not exist, the loader
MUST report a redacted, actionable error. It MUST NOT search arbitrary parent,
home, or repository directories.

New integrations MUST NOT add a current-working-directory fallback. Schwab's
existing `./secure_schwabdev.ecfg` fallback is a compatibility exception. Its
possible deprecation is a separate decision.

Path selection is not secret decryption. Diagnostic output MAY report the
selected path and configuration source, but MUST NOT expose encrypted contents,
passwords, tokens, keys, or decrypted values.

## 6. Loading and in-memory handling

1. Decryption MUST occur only when a process needs the credentials.
2. Decrypted values MUST remain in process memory and MUST NOT be written to
   temporary files, journals, CSV output, manifests, or logs.
3. Provider adapters SHOULD convert the decrypted dictionary into a validated,
   provider-specific immutable configuration object.
4. Missing, blank, malformed, or unexpected required fields MUST be rejected
   before an external request or durable output is created.
5. Errors MUST identify the missing field or corrective action without
   including secret values.
6. Debug representations, exception messages, and telemetry MUST redact all
   secret-bearing fields.

## 7. Machine and service registry

This registry contains identifiers and ownership only. It MUST never contain
credential values.

| Service | Owning machine | Default file | Override variable | Expected secret fields | Status |
| --- | --- | --- | --- | --- | --- |
| Schwab | MasterBot only | `secure_schwabdev.ecfg` | `MB_SCHWAB_ECFG` | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_TOKEN_DB_FERNET_KEY`; callback and token-database configuration are also required | Implemented |
| Pushover | Only a machine that sends notifications; initially El-Cheapo if scanner notifications are re-enabled | `secure_pushover.ecfg` | `MB_PUSHOVER_ECFG` | `PUSHOVER_APP_TOKEN`, `PUSHOVER_USER_KEY` | Planned; notifications disabled until valid credentials exist |
| Massive API | MasterBot only | `secure_massive.ecfg` | `MB_MASSIVE_ECFG` | `MASSIVE_API_KEY` | Planned |
| Massive flat files/S3 | MasterBot only | `secure_massive.ecfg` unless a later review separates it | `MB_MASSIVE_ECFG` | Provider-issued S3 access fields; exact names deferred until integration | Planned |

Schwab access and refresh tokens remain in Schwabdev's encrypted token database,
not in the `.ecfg` file. MasterBot remains the sole Schwab client and token owner;
the token database MUST NOT be copied to El-Cheapo.

Massive website-login credentials are outside this contract. Programmatic API
access uses an API key; flat-file/S3 access uses separate provider-issued
machine credentials.

## 8. Required and optional integrations

A process for which a credential-backed service is required MUST fail closed
before external side effects or durable run registration when credentials are
missing, invalid, or cannot be decrypted.

An optional integration MAY disable itself cleanly. It MUST emit a redacted
status stating that the capability was skipped or disabled. Pushover
notifications are optional unless a later operational contract explicitly makes
them a launch requirement.

Fallback to plaintext credentials is prohibited in both cases.

## 9. Credential lifecycle

For every provider integration, implementation and later User Notes must define:

1. credential issuance and minimum required scope;
2. encrypted-file creation or update;
3. validation that does not reveal the value;
4. rotation and verification of the replacement;
5. revocation or expiration of the former credential;
6. response to suspected disclosure; and
7. retirement of unused credentials and files.

The safe rotation order is create replacement, update the encrypted file,
validate the replacement, and then revoke the prior credential unless the
provider's security procedure requires immediate revocation.

If a credential reaches Git history, logs, screenshots, tickets, or another
untrusted location, encryption-at-rest policy is no longer sufficient. The
credential must be revoked or expired, the exposed artifact must be remediated,
and repository-host cleanup must be completed where applicable.

## 10. Source-control and test requirements

Repositories that consume credentials MUST ignore their service `.ecfg` files
and local credential setup files. A tracked example file MAY document key names
and disabled settings, but MUST contain unmistakable placeholders and no usable
credential.

Tests MUST use temporary files with synthetic values or injected mappings.
Tests MUST NOT depend on a developer's vault, real provider account, or active
credential. Tests of error messages and diagnostics SHOULD assert that secret
values are absent.

Before publishing or tagging a release, maintainers SHOULD inspect both the
working tree and reachable Git history for accidental credentials.

## 11. Compatibility and migration

The existing Schwab implementation remains valid:

- `MB_SCHWAB_ECFG` and `%MB_VAULT%\secure_schwabdev.ecfg` remain supported;
- the current-directory fallback remains temporarily for compatibility;
- Schwab tokens remain in the separately encrypted Schwabdev database; and
- `mb-schwab-auth` remains the explicit authorization and status interface.

Pushover's former plaintext environment-script mechanism is retired. Pushover
remains disabled until a service-specific encrypted loader, tests, and operator
procedure are implemented.

Massive credential handling is a design reservation, not an implemented
capability. No document should imply that Massive acquisition is operational
until code and validation evidence exist.

## 12. Consequences

This decision deliberately adds a password prompt to human-started secure
processes and requires service-specific loaders. In return, it limits credential
exposure, reduces cross-service blast radius, permits independent rotation, and
prevents an application from receiving unrelated secrets.

The contract does not make `.ecfg` files safe to publish. Encryption is one
control within a larger system of least privilege, source-control exclusion,
redacted diagnostics, rotation, and machine ownership.

## 13. Change control

Changes to storage format, resolution precedence, machine ownership,
unattended decryption, or plaintext fallback policy require an explicit update
to this contract and a corresponding entry in the canonical `mb_package`
decision register.

Provider-specific field additions that preserve this contract MAY be documented
with the provider implementation. User Notes should be added only after the
commands and failure behavior have been validated.
