---
status: pending
priority: p2
issue_id: "006"
tags: [code-review, performance, pwa, service-worker]
dependencies: ["004"]
---

# Add Cache-Busting and Re-enable Service Worker

## Problem Statement

The service worker (`sw.js`) is in self-destruct mode — it unregisters itself and clears all caches on activate (lines 1-13). This was intentional (stale cache issues during development) but means zero offline capability. The underlying problem is that `style.css` and `components.js` have no cache-busting identifiers, so the SW had no way to know when files changed.

## Findings

- `sw.js` lines 1-13: self-destruct code, `return` statement makes all caching code dead
- `sw.js` lines 15-53: correct caching implementation (network-first for API, cache-first for assets)
- `app.py` already serves `index.html` with `Cache-Control: no-cache` — the index always fetches fresh
- Over HTTP (not HTTPS), the `caches` API is unavailable — JS cannot clear SW caches programmatically
- A Python-side fingerprint function (MD5 hash query params) solves this permanently

## Proposed Solutions

### Solution 1: Python-side fingerprint + Jinja2 templating (RECOMMENDED)
```python
# In app.py, at startup
def fingerprint_static(static_dir: Path) -> dict[str, str]:
    files = ['style.css', 'components.js', 'sw.js']
    return {
        f'/{f}': f'/{f}?v={hashlib.md5((static_dir/f).read_bytes()).hexdigest()[:8]}'
        for f in files if (static_dir / f).exists()
    }
```
Serve `index.html` as Jinja2 template with hashed URLs injected.
- **Pros**: Zero frontend tooling, permanent fix, works with any file structure
- **Cons**: Adds Jinja2 dependency (already available via FastAPI)
- **Effort**: Small-Medium (1-2 hours)
- **Risk**: Low

### Solution 2: Add Vite for content-hashed filenames
- **Pros**: Automatic, elegant
- **Cons**: Adds Node.js build step, complicates vendored offline model
- **Effort**: High
- **Risk**: Medium

## Recommended Action

Solution 1. Re-enable the service worker caching code after fingerprinting is in place.

## Technical Details

- **Affected files**: `app.py`, `sw.js`, `index.html` (template conversion)
- **New dependency**: None (Jinja2 ships with FastAPI/Starlette)
- **SW cache list**: Update `ASSETS` array with hashed URLs

## Acceptance Criteria

- [ ] `fingerprint_static()` computes hashes for all JS/CSS files at startup
- [ ] `index.html` served as Jinja2 template with hashed asset URLs
- [ ] `sw.js` self-destruct block removed
- [ ] `sw.js` ASSETS list uses hashed URLs
- [ ] Assets cached for offline use
- [ ] Updating a file → new hash → SW installs new version automatically

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-04-07 | Research completed | Python-side fingerprinting is ~40 lines and eliminates a whole class of stale-cache bugs |
