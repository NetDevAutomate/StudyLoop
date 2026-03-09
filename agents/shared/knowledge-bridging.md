# Dynamic Knowledge Bridging

Configurable framework for leveraging a student's existing expertise to teach new concepts. Replaces hardcoded domain assumptions with a discoverable, trackable bridge system.

## How It Works

The student has deep expertise in one or more domains. The agent uses **structural analogies** between known and new concepts to accelerate learning. Bridges must map relational structure, not just surface features.

**Example:** A network engineer learning Spark:
- ECMP load balancing → Spark partition distribution (both distribute work across parallel processors for throughput)
- Control plane / data plane → Spark driver / executors (both separate coordination from processing)

## Default: Networking Bridges

If no custom domain is configured, the default bridge source is `network-bridges.md` — curated analogies from 30 years of networking experience mapped to data engineering, SQL, Spark, Glue, and SageMaker concepts.

This is the zero-configuration experience. It works immediately for the primary user.

## Configuring Custom Domains

For other users or additional bridge domains, run `/socratic-mentor configure` or manually edit `~/.config/studyctl/config.yaml`:

```yaml
knowledge_domains:
  primary: networking
  anchors:
    - concept: "ECMP load balancing"
      comfort: 10
    - concept: "BGP route propagation"
      comfort: 9
    - concept: "VLAN segmentation"
      comfort: 10
  secondary:
    - domain: "cooking"
      anchors:
        - "mise en place"
        - "flavour balancing"
        - "heat management"
  bridges: []  # populated dynamically via studyctl bridge add
```

### Interactive Configure Flow

When `/socratic-mentor configure` is invoked, the agent runs a discovery session:

**Step 1: Background Discovery**
"What's your professional background? What have you spent the most years working with?"
→ Captures primary expertise domain(s)

**Step 2: Comfort Mapping**
"Within [domain], what are the concepts you could explain in your sleep?"
→ Captures anchor concepts (high-comfort known concepts)

"Any hobbies, interests, or other skills where you have deep intuitive understanding?"
→ Captures secondary domains

**Step 3: Bridge Generation**
The agent identifies structural mappings between the student's known concepts and the target learning domain. It proposes an initial bridge table:

"Based on what you've told me, here are some concept bridges I think will work. Let me know if any feel wrong or forced:"

| Your Experience | Maps To | Why |
|---|---|---|
| [known concept] | [target concept] | [structural similarity] |

The student validates, rejects, or modifies each bridge.

**Step 4: Persist**
Validated bridges are saved via `studyctl bridge add` and written to config.

## Bridge Lifecycle

### Quality States

| State | Meaning | Agent Behaviour |
|---|---|---|
| `proposed` | Agent-generated, not yet validated | Use tentatively, ask if it helped |
| `validated` | Student confirmed it makes sense | Use confidently |
| `effective` | Used successfully in multiple sessions | Prioritise for this concept |
| `misleading` | Student reported confusion from the bridge | Stop using, try alternative |
| `rejected` | Student explicitly said it doesn't work | Never use again |

### Bridge Evolution

1. **Agent proposes** a bridge when introducing a new concept → quality: `proposed`
2. **Student validates** or rejects during session → quality: `validated` or `rejected`
3. **Agent tracks usage** — did the student grasp the concept faster with this bridge? → quality: `effective`
4. **Student generates** their own bridge → quality: `validated`, created_by: `student`

### Bridge Fading

As competence grows, bridges should become less explicit:

| Scaffolding Level | Bridge Behaviour |
|---|---|
| L1 Prompted | Provide explicit bridges: "Spark executors are like routers in your ECMP group." |
| L2 Assisted | Prompt for bridges: "What does this remind you of from your experience?" |
| L3 Independent | Expect student to generate bridges unprompted |
| L4 Teaching | Student should be able to create bridges for others |

### Student-Generated Bridges

When the student produces a good analogy during a session:

1. Acknowledge it: "That's a strong analogy — the structural mapping is [explanation]."
2. Record it: `studyctl bridge add "source" "target" -s domain -t domain -m "why"`
3. Re-use it in future reviews: personalised analogies increase engagement
4. Track effectiveness: does this student-generated bridge help in subsequent sessions?

## CLI Commands

```bash
# Add a bridge
studyctl bridge add "TCP three-way handshake" "OAuth token exchange" \
    -s networking -t security -m "both establish trust through multi-step negotiation"

# List bridges
studyctl bridge list                       # all bridges
studyctl bridge list -s networking         # from networking domain
studyctl bridge list -t spark              # to spark domain
studyctl bridge list -q effective          # only effective bridges
```

## Warm-Up Activation

Before introducing new material, spend 2 minutes activating relevant prior knowledge from the configured domain. This closes the transfer gap between old and new learning (Richland et al., 2019).

**Example:** Before teaching Spark DAGs:
"Before we dive into Spark DAGs, let's think about network topology for a moment. In your network designs, how do you handle dependency — making sure traffic flows in the right order through the right devices?"

This activates the relevant schema (dependency, flow, ordering) and makes the bridge to DAGs feel natural rather than forced.

## Key Research

| Study | Finding |
|---|---|
| Gentner (1983), Structure-Mapping Theory | Analogical reasoning maps relational structure, not surface features |
| Clement (1993), Bridging Analogies | Multi-hop bridges for concepts too distant from known domain |
| Gentner et al. (2004), Analogical Encoding | Comparing cases side-by-side improves transfer |
| Richland et al. (2019), *Current Directions in Psych Sci* | Warm-up activities activate prior knowledge, improve transfer |
| Blanchette & Dunbar (2000) | People produce better analogies when given persuasive goals |
