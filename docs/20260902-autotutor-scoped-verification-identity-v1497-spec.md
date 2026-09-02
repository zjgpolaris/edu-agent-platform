# AutoTutor Scoped Verification Identity & Bootstrap Readiness v1.49.7

- Status: Approved for implementation
- Date: 2026-09-02
- Scope: AutoTutor production verification control plane
- Predecessor: v1.49.6 production execution closure
- Target configuration: `v1.49.7-scoped-verification-identity`

## 1. Background

The v1.49.6 release is deployed in production at commit
`45ff74ab37f3f0b159c4dc8c18b6d25ef0bad944`. Its CI run passed and the public
runtime readiness endpoint confirms migration 016 and the AutoTutor rollout
writer are healthy.

The remaining production-verification path is not operationally safe enough:

1. The four AutoTutor verification endpoints currently require a broad admin
   JWT.
2. Admin JWTs expire after one hour, so they are unsuitable as a durable
   GitHub Actions machine credential.
3. A leaked verification credential would currently be useful against every
   admin endpoint.
4. The required GitHub Environment, reviewer rule, branch policy, variable and
   secret do not have a deterministic bootstrap attestation.
5. The production API cannot distinguish “runtime healthy” from “verification
   identity and CI bootstrap ready”.

This iteration closes that authorization and bootstrap gap before the four-stage
v1.49.6 production verification is executed.

## 2. Goal

Provide a least-privilege, rotatable machine identity that can call only the
four AutoTutor verification endpoints, plus a read-only bootstrap checker and
safe readiness signals that make missing production setup explicit.

## 3. Non-goals

- Do not create or modify a GitHub Environment, secret, variable or reviewer.
- Do not execute a production Canary or persist production evidence.
- Do not change normal user, teacher or admin JWT semantics.
- Do not grant the machine principal access to any other admin endpoint.
- Do not add a database migration.
- Do not expose raw tokens, token hashes, secret values or reviewer identities
  in API responses, logs, audit metadata or generated attestations.

## 4. Credential contract

### 4.1 Secret placement

The raw token exists only as the GitHub Environment secret
`AUTOTUTOR_PRODUCTION_API_TOKEN`. It must contain at least 32 characters.

Render stores only SHA-256 digests and public key identifiers:

- `EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_SHA256`
- `EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_KEY_ID`
- `EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_SHA256`
- `EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_KEY_ID`

Digests are exactly 64 lowercase hexadecimal characters. Key identifiers match
`[A-Za-z0-9._-]{1,32}`. A next slot is either fully configured or absent.

`EDU_AGENT_AUTOTUTOR_VERIFICATION_MACHINE_REQUIRED=true` enables the production
readiness gate. It is explicitly enabled by the production blueprint so the
change remains backward-compatible in local and historical test environments.

### 4.2 Authentication

Clients send the raw machine token using the existing Bearer header. The server
hashes the candidate with SHA-256 and compares it with both configured slots
using constant-time comparison.

A match produces an internal principal whose actor ID contains only the matched
key ID. The raw token and digest never enter the principal or response.

The scoped dependency also accepts a valid existing admin JWT. Teacher and
student JWTs receive 403. Missing, invalid, malformed and retired machine tokens
receive 401.

### 4.3 Authorization boundary

The scoped dependency is used by exactly these routes:

- `GET /api/admin/agent-runtime/autotutor-canary/verification`
- `POST /api/admin/agent-runtime/autotutor-canary/snapshots`
- `GET /api/admin/agent-runtime/autotutor-canary/evidence`
- `POST /api/admin/agent-runtime/autotutor-canary/evidence`

Every other admin endpoint retains `require_admin`. Because the static machine
token is not a JWT, those routes reject it.

### 4.4 Rotation

Rotation is a two-slot process:

1. Generate a new raw token and place its digest/key ID in the next slot.
2. Update the GitHub Environment secret to the new raw token.
3. Verify the next key works.
4. Promote next to current and clear the next slot.

Readiness reports only `missing`, `invalid`, `current_only` or `dual`; it never
reports digests.

## 5. Bootstrap attestation

Add `scripts/verify_autotutor_verification_environment.py`. It uses read-only
`gh api` calls and verifies:

- Environment `production-verification` exists.
- At least one required reviewer is configured.
- Deployments are limited to `main` through a protected-branch or matching
  custom-branch policy.
- Environment variable `AUTOTUTOR_PRODUCTION_API_BASE` exists.
- Environment secret `AUTOTUTOR_PRODUCTION_API_TOKEN` exists.

The output is a canonical, PII-free JSON document containing booleans, counts,
stable blocker codes, repository/environment names and a SHA-256 seal. It never
contains variable values, secret values, reviewer identities or token material.
`--require-go` exits non-zero when any contract item fails.

After an operator reviews the attestation, its digest is configured in Render as
`EDU_AGENT_AUTOTUTOR_VERIFICATION_BOOTSTRAP_SHA256`. The API exposes only whether
the attestation is configured, never its digest.

## 6. Readiness contract

The AutoTutor verification response adds a safe `verification_identity` object:

- `required`
- `configured`
- `valid`
- `rotation_state`
- `bootstrap_attested`
- `errors` using stable non-secret codes

When the machine gate is required, missing or invalid credential configuration
and a missing bootstrap attestation become explicit blockers:

- `verification_machine_credential_missing`
- `verification_machine_credential_invalid`
- `verification_bootstrap_not_attested`

The operations section maps the state to `api_credential`,
`credential_rotation` and `environment_bootstrap`. `production_verification_ready`
is true only when the normal verification contract has no blockers.

These fields are scoped to AutoTutor production verification and do not make the
general service readiness endpoint unhealthy.

## 7. Audit contract

Authentication failures and successful/failed route operations emit only safe
metadata. Required action names are:

- `autotutor.verification.auth_failed`
- `autotutor.verification.read`
- `autotutor.snapshot.create`
- `autotutor.evidence.read`
- `autotutor.evidence.persist`

Metadata may contain key ID, principal kind, phase, decision, evidence stage and
stable error class/reason. It must not contain request evidence, snapshots,
authorization headers, raw tokens or digests.

Audit persistence remains best-effort and must not change API availability.

## 8. Configuration and workflow

- Bump the default AutoTutor configuration and bucket salt to v1.49.7.
- Add machine identity variables to `.env.example` and `render.yaml`.
- Render digest and bootstrap values use `sync: false`; raw token is never added
  to Render configuration.
- Keep the GitHub workflow Bearer-header contract and update its expected default
  configuration version.
- Document bootstrap, token generation, hashing, rotation and execution in the
  runbook.

## 9. Verification plan

Deterministic smoke coverage must prove:

1. Current and next tokens authenticate with constant-time digest matching.
2. Short, malformed, absent and retired tokens fail.
3. A machine token can access the four scoped endpoints but is rejected by an
   unrelated admin endpoint.
4. Admin JWT compatibility remains intact and non-admin JWTs remain forbidden.
5. No raw token or digest appears in safe settings/readiness output.
6. Bootstrap fixtures cover GO and each missing environment control.
7. Bootstrap attestation hashes are deterministic and tampering is detectable.
8. Existing AutoTutor production verification, evidence and rollback suites
   continue to pass.
9. The release gate compiles and executes the new suites.

## 10. Acceptance criteria

- All code and documentation in this spec are present.
- The four-route authorization boundary is mechanically test-covered.
- Production blueprint requires the machine credential and bootstrap attestation.
- No database migration is introduced.
- `python scripts/release_gate.py --fast` passes.
- Frontend build passes if the readiness UI is changed.
- `git diff --check` passes and no secret material is committed.

## 11. Production handoff

After deploying v1.49.7, an operator must:

1. Create/configure the GitHub Environment controls.
2. Run the read-only bootstrap checker and review its sealed artifact.
3. Generate a token, store the raw value in GitHub and only its digest in Render.
4. Configure the reviewed bootstrap digest in Render and redeploy.
5. Confirm `production_verification_ready=true` through an authorized request.
6. Execute the v1.49.6 four-stage production verification workflow.

Only a final schema-v4 `GO` artifact plus verified rollback permits entry to the
v1.50 iteration.
