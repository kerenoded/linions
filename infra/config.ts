// config.ts — CDK-side config values. Single source of truth for all infra names
// and settings. Never inline these values in linions-stack.ts (STANDARDS.md §2.4).

export const config = {
  // Stack
  stackName: "LinionsStack",

  // S3 buckets
  episodesBucketName: "linions-episodes",
  kbBucketName: "linions-kb",

  // DynamoDB
  jobsTableName: "linions-jobs",
  jobsTtlAttribute: "ttl",

  // SQS
  dlqName: "linions-dlq",
  dlqRetentionDays: 14,
  orchestratorAsyncRetryAttempts: 0,

  // Lambda function names
  generateFunctionName: "linions-generate",
  orchestratorFunctionName: "linions-orchestrator",
  statusFunctionName: "linions-status",

  // Lambda sizing
  generateMemoryMb: 256,
  generateTimeoutSeconds: 10,
  orchestratorMemoryMb: 512,
  orchestratorTimeoutSeconds: 480,
  statusMemoryMb: 128,
  statusTimeoutSeconds: 5,

  // Bedrock model/profile settings
  sonnetModelId: "anthropic.claude-sonnet-4-6",
  sonnetInferenceProfileId: "eu.anthropic.claude-sonnet-4-6",
  drawingModelId: "anthropic.claude-opus-4-6-v1",
  drawingInferenceProfileId: "eu.anthropic.claude-opus-4-6-v1",
  kbEmbeddingModelId: "amazon.titan-embed-text-v2:0",
  kbEmbeddingDimensions: 1024,
  kbVectorIndexName: "linions-index-1024",
  kbName: "LinionsStack-linions-kb-v2",
  kbDataSourceName: "LinionsStack-linions-kb-source-v2",

  // CloudFront cache TTLs (seconds)
  episodeCacheTtlSeconds: 259200,      // 3 days — published episode JSON assets
  svgAssetCacheTtlSeconds: 259200,     // 3 days — published SVG art assets
  indexJsonCacheTtlSeconds: 0,         // always fresh — episodes/index.json
  staticAssetCacheTtlSeconds: 0,       // always fresh — JS/CSS module graphs across deploys
  indexHtmlCacheTtlSeconds: 0,         // always fresh — index.html

  // S3 path prefixes
  draftsPrefix: "drafts/",
  episodesPrefix: "episodes/",
} as const;
