# Knowledge graph primer (for this project)

Written 2026-10-22 so the design and ingestion logic can be reviewed with a shared vocabulary.

## 1. The basics

A knowledge graph stores **facts as connections**.
- A **node** is a thing: a question, a proposal, an integration design, a doc link, a diagram.
- An **edge** is a typed, directed relationship between two nodes: `Question --ASKED_IN--> Proposal`, `Design --DOCUMENTED_BY--> DocLink`.
- Both nodes and edges can carry **properties** (status, dates, counts, scores, where the fact came from).

A small piece of our graph:

```
(Question: "Is Tokenization in scope?") --ANSWERED {value: TRUE}--> (Proposal: A)
(Rule R-ecom-cards) --SUGGESTS--> (Design: web-sessions)
(Design: web-sessions) --HAS_CONSIDERATION--> (Consideration: "Use webhooks as the authoritative result")
(Design: web-sessions) --DOCUMENTED_BY--> (Doc: Sessions flow guide)
(Design: web-sessions) --ILLUSTRATED_BY--> (Diagram: web payment flow)
(Proposal: A) --USED_DESIGN {track: "Online payments"}--> (Design: web-sessions)
```

## 2. Why a graph instead of tables

Our central question is a *chain*: given these tags and answers → which designs apply → which considerations, docs and diagrams go with them → which past proposals used the same combination. In tables that is several joins you have to write each time. In a graph it is one traversal: start at the answers, follow edges. New kinds of facts (a new edge type) can be added without redesigning tables. The trade-off: it needs discipline about what nodes and edge types exist, otherwise it fills with duplicates and vague links.

(Postgres can store this: one table of nodes, one of edges with the properties as columns or JSON, and recursive queries for chains. At our size that is plenty.)

## 3. Where weights live: nodes, edges, or both?

**Mostly on edges.** A weight expresses "how good is this *connection*", e.g. "how well does web-sessions fit a deal with these answers", or "how good is this doc for this design". The same design can be right in one context and wrong in another, so the judgement belongs to the relationship, not to the design alone.

| Put it on... | What | Examples |
|---|---|---|
| **Edge** | Confidence that the relation is right; usefulness from feedback; evidence counts; status; provenance; last reviewed | rule → design, design → doc, design → diagram, question → design |
| **Node** | Intrinsic attributes that don't depend on a connection | Proposal quality score; doc link health (resolves? last changed); design status (draft/approved/retired); a question's lifecycle |

Rule of thumb: if the sentence is "X is good *for* Y", it is an edge property. If it is "X is healthy / current / good quality", it is a node property.

## 4. Rules as nodes ("reification")

A rule such as "channel includes ECOM AND payment methods mention cards → web-sessions" has several parts. To give it its own weight and feedback, make the **rule a node** that connects its conditions to the design. Then feedback can say "this rule fired and the result was wrong" and only that rule's edge to the design is adjusted, not the design in general.

## 5. How a weight works: counts, not a single number

Keeping counts means one data point can't swing a well-supported edge, and low evidence is visible. Each edge stores a prior plus accepted and rejected evidence:

confidence = (prior_good + accepted) / (prior_good + prior_bad + accepted + rejected)

| Edge | Start | After events | Confidence |
|---|---|---|---|
| Curated rule → web-sessions (prior 8 good, 2 bad) | 0.80, no evidence | kept in 3 completed proposals | 11/13 = 0.85 |
| same | | then replaced once by an IM | 11/14 = 0.79 |
| Derived edge learned from 1 proposal (prior 1 good, 1 bad) | 0.50 | kept in the next 4 proposals | 6/7 = 0.86 |
| same | | removed once in a later proposal | 6/8 = 0.75 |

Older evidence can be decayed so recent behaviour counts more. Curated edges start with a strong prior; derived edges start weak. We always show the evidence count next to the score, because "0.86 from 5 proposals" and "0.86 from a curator's say-so" mean different things.

A recommendation's rank combines: edge confidence, usefulness from feedback, recency, the quality of the source proposal, and the edge's status (retired edges are excluded; "under review" edges are down-weighted).

## 6. How ingestion adds to the graph

Take one completed proposal. Ingestion:
1. **Splits** it by the template's headings (no model needed).
2. **Reads structured data directly:** answered question → answer pairs from its question bank; doc URLs by pattern.
3. **Extracts the rest with a model,** under a fixed schema, and each proposed fact must cite the text it came from. Example sentence: "Payouts will use Adyen's managed payouts." → edge `Proposal --USED_DESIGN {track: Payouts}--> platforms-payouts`, with the section and quote as evidence.
4. **Resolves to existing nodes.** "managed payouts" maps to the canonical design node. If nothing matches, it goes to a review queue instead of creating a new node.
5. **Writes edges with provenance** (proposal, section, quote, extractor version, run ID) and updates evidence counts on edges that already exist.

So when a new proposal arrives, existing edges get *more evidence* (counts rise) and genuinely new relations appear as new edges. That is the "improves as people add proposals" behaviour.

## 7. Curated vs derived edges

- **Curated** (from the seed sheet): written by a person, strong prior, can be pinned so automation can't silently demote them.
- **Derived** (from proposals): weaker prior, strengthened by repeated evidence.
- Both live in the same graph. A flag decides whether derived edges are used, so we can compare the two.

## 8. Common pitfalls

- **Duplicate nodes** from near-identical wording (solved by resolving to canonical nodes and a review queue).
- **Vague edge types** ("RELATED_TO" everywhere) that make queries meaningless. Keep a small fixed set of edge types.
- **Stale facts** (doc changes, retired designs). Needs status, last-reviewed dates and link checks.
- **Over-trusting thin data** (two proposals). Show evidence counts and keep curated knowledge as the backbone early on.

## 9. Glossary

Node, edge, property, traversal (following edges to answer a question), provenance (where a fact came from), reification (turning a relationship into a node), canonical node (the one agreed node for a thing), prior (starting belief before evidence).
