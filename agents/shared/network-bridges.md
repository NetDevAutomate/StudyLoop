# Network → Data Engineering Bridges

Default bridge domain for the Socratic study mentor. These are the zero-configuration bridges that work immediately for students with networking backgrounds. For other domains, see `knowledge-bridging.md` and configure via `studyctl bridge add` or `~/.config/studyctl/config.yaml`.

Always use these analogies when explaining new concepts to leverage 30 years of infrastructure experience.

## Core Bridges

| Network Concept | Data Engineering Analog | Teaching Moment |
|---|---|---|
| Packet routing | Data partitioning | Route data to right node efficiently |
| Load balancing | Spark executors | Distribute work across workers |
| TCP vs UDP | Exactly-once vs at-least-once | Delivery guarantee tradeoffs |
| Network topology | DAG (Directed Acyclic Graph) | Dependency flow visualisation |
| QoS / Traffic shaping | Backpressure handling | Manage data flow rates |
| SNMP / Telemetry | Metrics / Observability | Monitor distributed systems |
| BGP route propagation | Event streaming | Changes propagate through system |
| Firewall rules | Data access policies | Who can see/modify what |
| VLAN segmentation | Data lake zones | Logical isolation (raw/curated/refined) |
| High availability | Fault tolerance | Survive node failures |
| DNS resolution | Schema registry | Name→structure mapping |
| NAT translation | Data transformation | Change format while preserving identity |
| Anycast routing | Distributed query engines | Route to nearest capable processor |

## AWS Glue ETL

| Network | Glue | Explanation |
|---|---|---|
| Protocol converter | Glue ETL job | Transform between formats |
| Network discovery | Glue Crawler | Auto-discover schema |
| DNS/Service registry | Glue Data Catalog | Central metadata repository |
| Traffic engineering | Job bookmarks | Track what's been processed |

## Amazon SageMaker

| Network | SageMaker | Explanation |
|---|---|---|
| Network provisioning | Training job | Spin up, run, tear down |
| Load balancer endpoint | Inference endpoint | Route requests to model |
| Auto-scaling group | Endpoint auto-scaling | Scale based on traffic |
| Blue/green deployment | Model variants | A/B testing, gradual rollout |

## Apache Spark

| Network | Spark | Explanation |
|---|---|---|
| Cluster of routers | Spark cluster | Distributed processing |
| Control plane | Driver | Coordinates work |
| Data plane | Executors | Actually process data |
| Broadcast traffic | Broadcast variables | Send read-only to all nodes |
| Multipath routing | Shuffle partitions | Redistribute across nodes |

## SQL Concepts

| Network | SQL | Explanation |
|---|---|---|
| Routing table lookup | Index scan | Fast path to specific data |
| Full network scan | Table scan | Check every row (expensive) |
| Route summarisation | Aggregation (GROUP BY) | Collapse detail into summary |
| ACL filtering | WHERE clause | Filter before processing |
| Spanning tree | Query plan tree | Optimal path through data |
| ECMP (equal-cost multipath) | Parallel query execution | Multiple paths simultaneously |
