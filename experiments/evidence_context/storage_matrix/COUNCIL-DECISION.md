# Storage council and decision

Grok 4.6 and Qwen3-Coder returned valid reviews of the full benchmark, diagnostic and
code packet. Fable 5.1 failed to return a JSON object. A single focused joint retry
returned only Qwen; its response omitted the requested storage reason. Fable failed
JSON again and Grok timed out. There is **no three-provider result consensus**.
The private artifacts preserve every attempt and the exact scope of each packet.

Both full-packet reviewers advised no migration. Grok emphasized that the SQLite scan
was a query-authoring result and that replica compression was not realistic scale.
Qwen emphasized missing concurrency and vector workloads. I accept those limits.

I reject assumptions that the tested engine settings are necessarily what would ship,
or that the microbenchmark represents the complete production access pattern. No
production design has been selected or installed. I also avoid substituting optimized
SQL into the frozen graph race: the diagnostic is separately labelled and preserved.

My decision: keep SQLite as canonical storage; use explicit relationship tables where
their information value is demonstrated. The real-answer failure warrants work on
retrieval completeness and claim applicability before more engine testing. A mixed
index remains an option behind an adapter if a measured need appears.

A future engine comparison should preregister optimized equivalent queries, include
unique text and meaningful degree distributions, and test the relevant durability,
concurrency and lifecycle behavior. It need not happen before the next useful context
experiment. The evidence does not justify more storage complexity simply to obtain
relationships that SQLite can already represent.
