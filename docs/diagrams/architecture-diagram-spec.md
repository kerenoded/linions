# Architecture Diagram Specification

This specification is intended for the project owner to create the diagram in draw.io,
then export as `docs/diagrams/architecture-diagram.gif`.

---

## Diagram layout

### Developer laptop (left / top-left)

- Box: "Browser" (`localhost:3000`)
  - Sub-label: "Prompt input -> Preview -> Share"
- Box: "Local Proxy Server" (SigV4)
  - All outbound AWS requests are SigV4-signed
  - Arrow from Browser -> Proxy, label: "POST /generate"
  - Arrow from Proxy -> Browser, label: "Poll /status"
  - Arrow from Proxy -> S3 (drafts prefix), label: "GET /drafts/*"
  - Arrow from S3 -> Proxy -> Browser, label: "Draft preview + publish to local repo"

### AWS Cloud (LinionsStack)

**Compute**

- Box: "Generate Lambda"
  - Arrow from Proxy -> Generate Lambda, label: "HTTPS (IAM auth)"
  - Arrow from Generate Lambda -> DynamoDB, label: "Create job (PENDING)"
  - Arrow from Generate Lambda -> Orchestrator Lambda, label: "Async invoke"
- Box: "Orchestrator Lambda" (largest box)
  - Inside: "Agents: Director, Animator, Drawing, Renderer"
  - Arrow from Orchestrator agents -> Bedrock (Claude models)
  - Arrow from pipeline end -> S3, label: "Write drafts/"
  - Arrow from Orchestrator -> DynamoDB, label: "Update stage labels"
- Box: "Status Lambda"
  - Arrow from Proxy -> Status Lambda, label: "HTTPS (IAM auth)"
  - Arrow from Status Lambda -> DynamoDB, label: "GetItem"

**AI Services**

- Box: "Amazon Bedrock" (Claude models)
  - Arrow from Orchestrator agents
- Box: "Bedrock Knowledge Base"
  - Arrow from Orchestrator (RAG Retrieval)
  - Arrow from KB -> S3 KB bucket, label: "~50 character docs"
- Box: "AWS AgentCore"
  - Dashed line to Orchestrator, label: "Shared session ID"

**Storage**

- Box: "S3 -- Episodes Bucket"
  - Two prefixes shown: `drafts/{user}/{uuid}/` and `episodes/{user}/{uuid}/`
- Box: "DynamoDB -- Jobs"
  - Label: "TTL: 24h"
- Box: "SQS -- Dead Letter Queue"
  - Arrow from Orchestrator Lambda -> SQS, label: "Failed jobs"

**CDN**

- Box: "CloudFront"
  - Arrow from CloudFront -> S3 (episodes prefix), label: "OAC origin"

### Viewers

- Box: "Browser"
  - Arrow from Browser -> CloudFront
  - Arrow from CloudFront -> S3 -> CloudFront -> Browser (serves gallery + episodes)

## Visual notes

- Use AWS service icons where available for visual clarity
- The orchestrator box should be the visual center of gravity
