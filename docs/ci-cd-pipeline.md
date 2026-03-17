# CI/CD Pipeline

Automated quality gates for the Socratic Study Mentor ecosystem.

## Workflow Overview

```
          push/PR              nightly 3am UTC         release tag v*
             │                      │                       │
             ▼                      ▼                       ▼
      ┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
      │  CI (tests)  │    │ Upstream Drift   │    │  Pre-Release     │
      │  lint+types  │    │ Detection        │    │  Gate            │
      └─────────────┘    └──────────────────┘    └──────────────────┘
                                                          │
                                                          ▼ on success
                                                 ┌──────────────────┐
                                                 │  PyPI Publish    │
                                                 └──────────────────┘
                                                          │
                                                          ▼ on success
                                                 ┌──────────────────┐
                                                 │  Docker Build    │
                                                 │  + Push to GHCR  │
                                                 └──────────────────┘
```

## 1. CI (existing — enhanced)

**Trigger:** push to main, pull requests
**File:** `.github/workflows/ci.yml` (existing, add doctor step)

Current workflow runs lint, type checks, and pytest. Enhanced with:

```yaml
- name: Smoke test doctor
  run: |
    studyctl doctor --json | python -c "
      import json, sys
      results = json.load(sys.stdin)
      failures = [r for r in results if r['status'] == 'fail']
      if failures:
          for f in failures:
              print(f'FAIL: {f[\"category\"]}/{f[\"name\"]}: {f[\"message\"]}')
          sys.exit(1)
    "
```

## 2. Nightly: Upstream Drift Detection

**Trigger:** `cron: '0 3 * * *'` (3am UTC daily)
**File:** `.github/workflows/nightly-drift.yml`

Catches breaking changes from upstream dependencies between releases.

### Matrix

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest]
    python: ['3.12', '3.13']
```

### Steps

```yaml
steps:
  # 1. Fresh install from PyPI
  - uses: actions/setup-python@v5
    with:
      python-version: ${{ matrix.python }}
  - run: pip install 'studyctl[all]'

  # 2. Doctor check
  - name: Run studyctl doctor
    run: studyctl doctor --json > doctor-results.json
  - name: Assert doctor healthy
    run: |
      python -c "
        import json, sys
        results = json.load(open('doctor-results.json'))
        fails = [r for r in results if r['status'] == 'fail']
        if fails:
            print(f'{len(fails)} doctor checks failed:')
            for f in fails: print(f'  {f[\"name\"]}: {f[\"message\"]}')
            sys.exit(1)
        print('Doctor: all checks passed')
      "

  # 3. Simulate upgrade from previous release
  - name: Install previous release
    run: |
      CURRENT=$(pip show studyctl | grep Version | cut -d' ' -f2)
      pip install "studyctl<${CURRENT}"
  - name: Run upgrade
    run: studyctl upgrade --component packages --component database
  - name: Doctor after upgrade
    run: studyctl doctor

  # 4. Full test suite post-upgrade
  - name: Run tests
    run: pytest --tb=short -q

  # 5. Auto-open issue on failure
  - name: Open issue on failure
    if: failure()
    uses: actions/github-script@v7
    with:
      script: |
        const fs = require('fs');
        const results = JSON.parse(fs.readFileSync('doctor-results.json', 'utf8'));
        const fails = results.filter(r => r.status === 'fail');
        const body = [
          '## Nightly drift detection failure',
          `**OS:** ${{ matrix.os }} | **Python:** ${{ matrix.python }}`,
          `**Date:** ${new Date().toISOString().split('T')[0]}`,
          '',
          '### Failed checks',
          ...fails.map(f => `- **${f.name}**: ${f.message}`),
          '',
          `[Workflow run](${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID})`
        ].join('\n');
        await github.rest.issues.create({
          owner: context.repo.owner,
          repo: context.repo.repo,
          title: `Nightly drift: ${fails.length} check(s) failed on ${{ matrix.os }}/py${{ matrix.python }}`,
          body: body,
          labels: ['ci', 'upstream-drift']
        });
```

## 3. Pre-Release Gate

**Trigger:** release tags (`v*`), manual workflow dispatch
**File:** `.github/workflows/pre-release.yml`

Must pass before PyPI publish proceeds.

### Steps

```yaml
steps:
  # 1. Test fresh install
  - run: pip install 'studyctl[all]'
  - run: studyctl doctor
  - run: pytest --tb=short -q

  # 2. Test upgrade from N-1
  - name: Install previous stable
    run: pip install 'studyctl[all]<${{ github.ref_name }}'
  - name: Upgrade to this release
    run: pip install dist/*.whl
  - name: Doctor after upgrade
    run: studyctl doctor
  - name: Tests after upgrade
    run: pytest --tb=short -q

  # 3. Build and test Docker image
  - name: Build Docker image
    run: docker build -t studyctl-web:test -f docker/Dockerfile .
  - name: Doctor inside container
    run: docker run --rm studyctl-web:test studyctl doctor --json
  - name: Health check
    run: |
      docker run -d --name test-web -p 8567:8567 studyctl-web:test
      sleep 5
      curl -f http://localhost:8567 || exit 1
      docker stop test-web

  # 4. Publish to PyPI (only if all above pass)
  - name: Publish to PyPI
    if: startsWith(github.ref, 'refs/tags/v')
    run: uv publish
    env:
      UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
```

## 4. Docker Image Pipeline

**Trigger:** successful PyPI publish, Dockerfile changes on main
**File:** `.github/workflows/docker.yml`

### Steps

```yaml
steps:
  - name: Build image
    run: |
      docker build \
        -t ghcr.io/netdevautomate/studyctl-web:${{ github.ref_name }} \
        -t ghcr.io/netdevautomate/studyctl-web:latest \
        -f docker/Dockerfile .

  - name: Doctor inside container
    run: |
      docker run --rm ghcr.io/netdevautomate/studyctl-web:latest \
        studyctl doctor --json --category core --category database

  - name: Web health check
    run: |
      docker run -d --name hc -p 8567:8567 \
        ghcr.io/netdevautomate/studyctl-web:latest
      sleep 5
      curl -f http://localhost:8567 || exit 1
      docker stop hc

  - name: TTS health check
    run: |
      docker run --rm ghcr.io/netdevautomate/studyctl-web:latest \
        python -c "
          from studyctl.tts import generate_audio
          audio = generate_audio('Hello world')
          assert len(audio) > 0, 'TTS generated empty audio'
          print('TTS: OK')
        "

  - name: Push to GHCR
    run: |
      echo ${{ secrets.GITHUB_TOKEN }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin
      docker push ghcr.io/netdevautomate/studyctl-web:${{ github.ref_name }}
      docker push ghcr.io/netdevautomate/studyctl-web:latest
```

## 5. Local Development with `act`

Run the same workflows locally on macOS before pushing.

### Setup

```bash
brew install act
```

### Usage

```bash
# Run CI tests locally
act push

# Run nightly drift detection locally
act schedule -j nightly-drift

# Run pre-release gate locally
act workflow_dispatch -W .github/workflows/pre-release.yml

# Run Docker build+test locally
act workflow_dispatch -W .github/workflows/docker.yml
```

### Limitations

- `act` uses Docker containers, so macOS-specific tests (launchd, Keychain)
  run in Linux containers instead
- GitHub API calls (auto-open issue) are skipped locally by default
- Docker-in-Docker may need `--privileged` flag

## Version Compatibility

`studyctl upgrade` performs a pre-flight check using `compatibility.json`:

```json
{
  "0.3.0": {
    "min_python": "3.12",
    "breaking": {
      "notebooklm-py": {
        "min": "0.3.4",
        "max": "0.3.99",
        "note": "0.4.0 changes generation API"
      }
    },
    "compatible": {
      "pymupdf": ">=1.23",
      "sentence-transformers": ">=2.2",
      "fastapi": ">=0.100"
    }
  }
}
```

Hosted at:
- PyPI package metadata (bundled with each release)
- GitHub raw URL (fallback): `https://raw.githubusercontent.com/NetDevAutomate/socratic-study-mentor/main/compatibility.json`

The upgrade command:
1. Fetches the target version's compatibility data
2. Compares against installed dependency versions
3. Warns on known breaking changes with migration instructions
4. `--dry-run` shows the full diff without making changes
