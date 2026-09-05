Independently label these synthetic source/target cases BEFORE experiment execution. You are not given coordinator labels, condition names, or prior scores. Use only the policy below, challenge any ambiguous policy rather than guessing. In reasons output EXACTLY one string per case in format C01|A or B or none|brief justification. Put broader design critique in other fields. No markdown fences. A/B is an opaque fixture choice, not a real product recommendation. Give all12 case labels. Policy: a supported choice requires source.kind artifact, exactly one [observed]...[/observed] block, exactly one declaration each for revision/workload/environment/metric, those values exactly equal complete target fields, and exactly one winner declaration with value A or B. Any missing/duplicate/mismatching required declaration, report kind, or malformed/multiple block means none. Lines outside the block are not observed declarations. All provenance kinds are fixture-supplied, NOT authenticated.
Proposed experiment: same frozen prior answer prompt in all model calls,12cases twice=24calls. Show source/target plus checked scripted proposals, including omissions/corruptions; no new LLM extraction. Compare that one draft with TWO deterministic release paths offline: conservative path uses only matched candidate fields; source-adapter path reparses the original source's narrow grammar independently of candidate values. Reparse is a separate, explicit derivation, never a silent repair of the candidate. Both feed the existing decision policy; model prose is not released. Pre-register strict JSON and complete-fence-only parsing as separate measurements. Code conformance is not efficacy. Positive cases test false blocking, especially extractor omission despite complete source. Cases are developer-authored and these model reviews are not independent human labels. Please identify any weakness before execution.
[
  {
    "id": "C01",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C02",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-west\nmetric: restart correctness\nwinner: A\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C03",
    "source": {
      "id": "S1",
      "kind": "report",
      "text": "[observed]\nrevision: r2\nworkload: eight writers\nenvironment: fixture-local\nmetric: reopen correctness\nwinner: B\n[/observed]\nThis is an agent report, not captured test output."
    },
    "target": {
      "revision": "r2",
      "workload": "eight writers",
      "environment": "fixture-local",
      "metric": "reopen correctness"
    }
  },
  {
    "id": "C04",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C05",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\n[/observed]\nwinner: B\nrevision: r99"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C06",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C07",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\n[/observed]\n[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C08",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: two writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C09",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: A\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C10",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r7\nworkload: six writers\nenvironment: fixture-east\nmetric: restart correctness\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r7",
      "workload": "six writers",
      "environment": "fixture-east",
      "metric": "restart correctness"
    }
  },
  {
    "id": "C11",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nrevision: r1\nrevision: r2\nworkload: eight writers\nenvironment: fixture-local\nmetric: reopen correctness\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r2",
      "workload": "eight writers",
      "environment": "fixture-local",
      "metric": "reopen correctness"
    }
  },
  {
    "id": "C12",
    "source": {
      "id": "S1",
      "kind": "artifact",
      "text": "[observed]\nworkload: eight writers\nenvironment: fixture-local\nmetric: reopen correctness\nwinner: B\n[/observed]"
    },
    "target": {
      "revision": "r2",
      "workload": "eight writers",
      "environment": "fixture-local",
      "metric": "reopen correctness"
    }
  }
]
