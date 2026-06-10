# FileVault — Security Audit & Penetration Test Evidence
**Auditor:** Dahirou Bachar  
**Date:** 2026-06-10  
**Scope:** FileVault web application (Flask/PostgreSQL), deployed on Railway

---

## 1. Methodology

Manual black-box and grey-box testing performed against the local development instance and the Railway production deployment. Tests follow OWASP Top 10 (2021) categories. Each finding documents: test description, evidence, result, and remediation applied.

---

## 2. Authentication & Session Management

### 2.1 Brute-Force Login (OWASP A07 – Identification & Authentication Failures)

**Test:** Sent 20 rapid POST requests to `/auth/login` with incorrect passwords using `curl` in a loop.

```bash
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/auth/login \
    -d "email=target@example.com&password=wrong$i"
done
```

**Result:** Requests 11–20 returned `429 Too Many Requests`. Flask-Limiter enforces `10 per minute; 50 per hour` on `/auth/login`.

**Status:** MITIGATED ✅

---

### 2.2 MFA Bypass Attempt

**Test:** After supplying valid credentials, attempted to skip the `/auth/mfa-verify` step by navigating directly to `/dashboard`.

**Result:** Flask-Login `@login_required` + session state check redirects to MFA verify page. Direct navigation without completing TOTP fails.

**Status:** MITIGATED ✅

---

### 2.3 Account Enumeration via Login Error

**Test:** Submitted login with known email (registered) vs. unknown email and compared HTTP responses and timing.

**Result:** Both return the same generic message: *"Invalid credentials"*. No distinction between unknown email and wrong password.

**Status:** MITIGATED ✅

---

## 3. File Access Control (OWASP A01 – Broken Access Control)

### 3.1 IDOR — Access Another User's File

**Test:** Logged in as User B. Used User A's file UUID obtained from the URL and attempted to download it:

```bash
curl -s -b "session=<user_b_cookie>" \
  -X POST http://localhost:5000/decrypt/<user_a_uuid> \
  -d "password=UserBPassword"
```

**Result:** Returns `403 Forbidden`. Access is checked against `file.user_id` and the `FileShare` table before any data is read.

**Status:** MITIGATED ✅

---

### 3.2 IDOR — Delete Another User's File

**Test:** Sent DELETE request to `/file/<user_a_uuid>` while authenticated as User B.

**Result:** Returns `403 Forbidden`. Owner check enforced: `if rec.user_id != current_user.id and not current_user.is_admin`.

**Status:** MITIGATED ✅

---

### 3.3 Privilege Escalation — Admin Route Access

**Test:** Authenticated as a regular user and accessed `/admin/users`.

**Result:** Redirected to dashboard with "Access denied." flash. `@login_required` + `current_user.is_admin` guard on all admin routes.

**Status:** MITIGATED ✅

---

## 4. Injection Attacks (OWASP A03)

### 4.1 SQL Injection — Login Form

**Test:** Submitted `' OR '1'='1` as both email and password fields.

```
email: ' OR '1'='1'--
password: anything
```

**Result:** SQLAlchemy ORM with parameterised queries. Input treated as a literal string, no rows returned, login fails normally.

**Status:** MITIGATED ✅

---

### 4.2 XSS — File Name Injection

**Test:** Uploaded a file named `<script>alert(1)</script>.txt` and viewed the file list page.

**Result:** Jinja2 auto-escaping renders the filename as `&lt;script&gt;alert(1)&lt;/script&gt;.txt`. No script executes.

**Status:** MITIGATED ✅

---

### 4.3 Path Traversal — File Download

**Test:** Attempted to download `/etc/passwd` by manipulating the file UUID parameter and crafting direct requests to the upload folder path.

```bash
curl -s "http://localhost:5000/download/../../../etc/passwd"
```

**Result:** Files are served only by UUID lookup in the database; physical paths are never derived from user input. `../../` traversal returns 404.

**Status:** MITIGATED ✅

---

## 5. Cryptography (OWASP A02 – Cryptographic Failures)

### 5.1 Encryption at Rest

**Test:** Inspected the `vault_uploads/` directory after uploading a plaintext `.txt` file.

**Result:** File on disk is Fernet-encrypted (AES-128-CBC + HMAC-SHA256). Reading the raw bytes returns ciphertext; original content is unrecoverable without the server key.

**Status:** IMPLEMENTED ✅

---

### 5.2 Per-File Key Isolation (HKDF)

**Architecture note:** Each file uses a unique 32-byte AES key derived via HKDF-SHA256 from the master `ENCRYPTION_KEY` and the file's randomly generated `stored_name`. Compromise of one file's key does not expose other files.

```python
HKDF(algorithm=SHA256(), length=32, info=stored_name.encode()).derive(master_key)
```

**Status:** IMPLEMENTED ✅

---

### 5.3 Password Storage

**Test:** Queried the `users` table in PostgreSQL directly and examined the `password_hash` column.

**Result:** Values are bcrypt hashes (`$2b$12$...`). Werkzeug's `generate_password_hash` uses bcrypt by default with cost factor 12.

**Status:** IMPLEMENTED ✅

---

## 6. Rate Limiting (OWASP A04 – Insecure Design)

All sensitive endpoints are protected by Flask-Limiter (v4.1.1):

| Endpoint | Limit |
|---|---|
| `POST /auth/login` | 10/min · 50/hr |
| `POST /auth/register` | 5/min · 20/hr |
| `POST /auth/mfa-verify` | 5/min · 20/hr |
| `POST /upload` | 20/hr |
| `POST /decrypt/<uuid>` | 5/min |
| `POST /preview-auth/<uuid>` | 10/min |
| `POST /api/share/<uuid>` | 30/hr |
| `POST /fim/check/<uuid>` | 30/min |
| `POST /fim/baseline/<uuid>/capture` | 30/min |
| `POST /fim/baseline/<uuid>/reset` | 30/min |

**Test:** Exceeded the `/decrypt/<uuid>` limit (5 per minute) using a loop of 10 requests.

```bash
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    http://localhost:5000/decrypt/<uuid> -d "password=test"
done
# Output: 200 200 200 200 200 429 429 429 429 429
```

**Status:** MITIGATED ✅

---

## 7. File Integrity Monitoring (FIM) — Tamper Detection

### 7.1 Direct Disk Modification

**Test:** Manually edited a file in `vault_uploads/` using a hex editor to change one byte, then waited for the scheduled integrity check (60-second interval).

**Result:**
- SHA-256 hash mismatch detected.
- `IntegrityAlert` record created with severity `high` and status `open`.
- Real-time SocketIO notification pushed to the file owner's browser.
- Email alert sent to the registered `alert_email` address within 30 seconds.

**Status:** DETECTED ✅

---

### 7.2 File Deletion Attack

**Test:** Deleted a monitored file from `vault_uploads/` directly on disk.

**Result:** Watchdog (`watchdog` library via `integrity_watchdog.py`) detected the `on_deleted` event immediately and triggered the integrity check pipeline. Alert raised before the next scheduled check.

**Status:** DETECTED ✅

---

## 8. Security Headers

**Test:** Used `curl -I` to inspect response headers.

```bash
curl -I https://<railway-domain>/
```

**Findings:**

| Header | Value | Assessment |
|---|---|---|
| `X-Frame-Options` | `SAMEORIGIN` (Flask default) | ✅ |
| `X-Content-Type-Options` | Set by Railway proxy | ✅ |
| `Strict-Transport-Security` | Set by Railway (HTTPS enforced) | ✅ |
| `Content-Security-Policy` | Not explicitly set | ⚠️ Acceptable for MVP |

**Recommendation:** Add a CSP header in a future iteration.

---

## 9. Summary of Findings

| # | Category | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Auth | Brute-force login | High | Mitigated |
| 2 | Auth | MFA bypass | High | Mitigated |
| 3 | Auth | Account enumeration | Medium | Mitigated |
| 4 | Access Control | IDOR file download | High | Mitigated |
| 5 | Access Control | IDOR file delete | High | Mitigated |
| 6 | Access Control | Privilege escalation | High | Mitigated |
| 7 | Injection | SQL injection | Critical | Mitigated |
| 8 | Injection | XSS via filename | Medium | Mitigated |
| 9 | Injection | Path traversal | High | Mitigated |
| 10 | Crypto | Plaintext storage on disk | Critical | Mitigated |
| 11 | Crypto | Shared encryption key | Medium | Mitigated (per-file HKDF) |
| 12 | Design | Missing rate limits | Medium | Mitigated |
| 13 | FIM | Tamper detection accuracy | — | Verified working |

**All critical and high findings are mitigated in the current production deployment.**
