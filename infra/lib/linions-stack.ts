import * as path from "node:path";

import * as cdk from "aws-cdk-lib";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as lambdaDestinations from "aws-cdk-lib/aws-lambda-destinations";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as s3vectors from "aws-cdk-lib/aws-s3vectors";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";

import { config } from "../config";

const PYTHON_RUNTIME = lambda.Runtime.PYTHON_3_11;
const PYTHON_BUNDLING_EXCLUDES = [
  ".git/**",
  ".venv/**",
  "node_modules/**",
  "**/__pycache__/**",
  "**/*.pyc",
  ".cache/**",
  "coverage/**",
  "cdk.out/**",
  "infra/**",
  "proxy/**",
  "tests/**",
  "episodes/**",
  "knowledge-base/**",
  "scripts/**",
  "README.md",
  "CLAUDE.md",
  "CLINE.md",
  "DESIGN.md",
  "PHASES.md",
  "REQUIREMENTS.md",
  "STANDARDS.md",
];

type PythonLambdaCodeProps = {
  bundleLabel: string;
  copyPaths: string[];
  pipCacheHostDir: string;
  projectRoot: string;
  requirementsPath?: string;
};

const buildAssetCopyCommand = (relativePath: string): string =>
  [`mkdir -p "/asset-output/${path.dirname(relativePath)}"`, `cp -R "/asset-input/${relativePath}" "/asset-output/${relativePath}"`].join(
    " && ",
  );


const buildRequirementsInstallCommand = (requirementsPath?: string): string => {
  if (!requirementsPath) {
    return 'echo "[bundle:$BUNDLE_LABEL] no third-party Python dependencies configured"';
  }

  return [
    // AWS Lambda's Python runtime already ships with boto3/botocore. Filtering
    // those lines out here avoids reinstalling the AWS SDK on every synth/deploy.
    `sed -E '/^[[:space:]]*(#|$)/d;/^[[:space:]]*boto3([[:space:]]|[<>=!~].*)?$/d' "/asset-input/${requirementsPath}" > /tmp/runtime-requirements.txt;`,
    "if [ ! -s /tmp/runtime-requirements.txt ]; then",
    'echo "[bundle:$BUNDLE_LABEL] using AWS Lambda runtime boto3; no bundled pip install required";',
    "else",
    "if [ -f /asset-input/requirements.lock ]; then",
    // /tmp here is inside the bundling container, not the repo. It is the
    // writable scratch space for transient files created during packaging.
    `sed -E 's/^([A-Za-z0-9_.-]+)\\[[^]]+\\](==.*)$/\\1\\2/' /asset-input/requirements.lock > /tmp/requirements.lambda.constraints.txt && pip install --prefer-binary --no-compile -r /tmp/runtime-requirements.txt -c /tmp/requirements.lambda.constraints.txt -t /asset-output;`,
    "else",
    "pip install --prefer-binary --no-compile -r /tmp/runtime-requirements.txt -t /asset-output;",
    "fi;",
    "fi",
  ].join(" ");
};

const buildInstalledPackageCleanupCommand = (): string =>
  [
    // dist-info and egg-info are package metadata, not runtime modules. Removing
    // them keeps Lambda bundles smaller without affecting imports used here.
    "find /asset-output -mindepth 1 -maxdepth 1 -type d",
    "\\(",
    '-name "*.dist-info"',
    "-o",
    '-name "*.egg-info"',
    "\\)",
    "-exec rm -rf {} +",
  ].join(" ");

const buildBundlingCommand = ({
  bundleLabel,
  copyPaths,
  requirementsPath,
}: Pick<PythonLambdaCodeProps, "bundleLabel" | "copyPaths" | "requirementsPath">): string =>
  [
    "set -euo pipefail",
    `BUNDLE_LABEL="${bundleLabel}"`,
    "mkdir -p /tmp/pip-cache",
    "bundle_start=$SECONDS",
    'echo "[bundle:$BUNDLE_LABEL] started at $(date -u +%Y-%m-%dT%H:%M:%SZ)"',
    "copy_start=$SECONDS",
    ...copyPaths.map(buildAssetCopyCommand),
    'echo "[bundle:$BUNDLE_LABEL] copied source files in $((SECONDS - copy_start))s"',
    "deps_start=$SECONDS",
    buildRequirementsInstallCommand(requirementsPath),
    buildInstalledPackageCleanupCommand(),
    'echo "[bundle:$BUNDLE_LABEL] dependency step finished in $((SECONDS - deps_start))s"',
    'echo "[bundle:$BUNDLE_LABEL] total bundle time $((SECONDS - bundle_start))s"',
  ].join(" && ");

const buildPythonLambdaCode = ({
  bundleLabel,
  copyPaths,
  pipCacheHostDir,
  projectRoot,
  requirementsPath,
}: PythonLambdaCodeProps): lambda.Code =>
  lambda.Code.fromAsset(projectRoot, {
    exclude: PYTHON_BUNDLING_EXCLUDES,
    bundling: {
      image: PYTHON_RUNTIME.bundlingImage,
      platform: "linux/amd64",
      user: "root",
      environment: {
        // /tmp is container-local scratch storage. It keeps transient cache and
        // constraints files out of the repo while remaining writable in Docker.
        HOME: "/tmp",
        PIP_CACHE_DIR: "/tmp/pip-cache",
        PIP_DISABLE_PIP_VERSION_CHECK: "1",
      },
      volumes: [
        {
          hostPath: pipCacheHostDir,
          containerPath: "/tmp/pip-cache",
        },
      ],
      command: [
        "bash",
        "-lc",
        buildBundlingCommand({
          bundleLabel,
          copyPaths,
          requirementsPath,
        }),
      ],
    },
  });

export class LinionsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const account = cdk.Stack.of(this).account;
    const projectRoot = path.resolve(__dirname, "../../../");
    const pipCacheHostDir = path.join(projectRoot, ".cache", "pip");
    const lambdaPackagePaths = ["pipeline/__init__.py", "pipeline/lambdas/__init__.py"];
    const sharedRuntimePaths = [
      "pipeline/config.py",
      "pipeline/shared",
      "pipeline/storage",
      "pipeline/lambdas/shared",
    ];

    const generateCode = buildPythonLambdaCode({
      bundleLabel: "GenerateFunction",
      projectRoot,
      pipCacheHostDir,
      copyPaths: [...lambdaPackagePaths, ...sharedRuntimePaths, "pipeline/lambdas/generate"],
      requirementsPath: "pipeline/lambdas/generate/requirements.txt",
    });

    const statusCode = buildPythonLambdaCode({
      bundleLabel: "StatusFunction",
      projectRoot,
      pipCacheHostDir,
      copyPaths: [...lambdaPackagePaths, ...sharedRuntimePaths, "pipeline/lambdas/status"],
      requirementsPath: "pipeline/lambdas/status/requirements.txt",
    });

    const orchestratorCode = buildPythonLambdaCode({
      bundleLabel: "OrchestratorFunction",
      projectRoot,
      pipCacheHostDir,
      copyPaths: [
        ...lambdaPackagePaths,
        ...sharedRuntimePaths,
        "pipeline/agents/__init__.py",
        "pipeline/models",
        "pipeline/agents/director",
        "pipeline/agents/animator",
        "pipeline/agents/drawing",
        "pipeline/agents/renderer",
        "pipeline/media",
        "pipeline/validators",
        "pipeline/lambdas/orchestrator",
        "frontend/public/linai-template.svg",
        "frontend/public/obstacles",
        "frontend/public/backgrounds",
      ],
      requirementsPath: "pipeline/lambdas/orchestrator/requirements.txt",
    });

    const episodesBucket = new s3.Bucket(this, "EpisodesBucket", {
      bucketName: `${config.episodesBucketName}-${account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
    });

    const kbBucket = new s3.Bucket(this, "KnowledgeBaseBucket", {
      bucketName: `${config.kbBucketName}-${account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
    });

    const jobsTable = new dynamodb.Table(this, "JobsTable", {
      tableName: config.jobsTableName,
      partitionKey: {
        name: "job-id",
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: config.jobsTtlAttribute,
    });

    const orchestratorDlq = new sqs.Queue(this, "OrchestratorDlq", {
      queueName: config.dlqName,
      retentionPeriod: cdk.Duration.days(config.dlqRetentionDays),
    });

    const lambdaBasicExecution = iam.ManagedPolicy.fromAwsManagedPolicyName(
      "service-role/AWSLambdaBasicExecutionRole",
    );

    const generateRole = new iam.Role(this, "GenerateRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [lambdaBasicExecution],
      description: "IAM role for linions-generate Lambda.",
    });

    const orchestratorRole = new iam.Role(this, "OrchestratorRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [lambdaBasicExecution],
      description: "IAM role for linions-orchestrator Lambda.",
    });

    const statusRole = new iam.Role(this, "StatusRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [lambdaBasicExecution],
      description: "IAM role for linions-status Lambda.",
    });

    const kbRole = new iam.Role(this, "KnowledgeBaseRole", {
      assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      description: "IAM role for Bedrock Knowledge Base access.",
    });

    const foundationModelArn = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "foundation-model",
      resourceName: config.kbEmbeddingModelId,
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
      account: "",
      region: cdk.Aws.REGION,
    });

    const sonnetModelArn = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "foundation-model",
      resourceName: config.sonnetModelId,
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
      account: "",
      region: "*",
    });

    const drawingModelArn = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "foundation-model",
      resourceName: config.drawingModelId,
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
      account: "",
      region: "*",
    });

    const sonnetInferenceProfileArn = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "inference-profile",
      resourceName: config.sonnetInferenceProfileId,
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
      account: cdk.Aws.ACCOUNT_ID,
      region: cdk.Aws.REGION,
    });

    const drawingInferenceProfileArn = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "inference-profile",
      resourceName: config.drawingInferenceProfileId,
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
      account: cdk.Aws.ACCOUNT_ID,
      region: cdk.Aws.REGION,
    });
    const lambdaLogRetention = logs.RetentionDays.TWO_WEEKS;
    const createLambdaLogGroup = (id: string, functionName: string): logs.LogGroup =>
      new logs.LogGroup(this, id, {
        logGroupName: `/aws/lambda/${functionName}`,
        retention: lambdaLogRetention,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
      });

    const generateFunctionLogGroup = createLambdaLogGroup(
      "GenerateFunctionLogGroup",
      config.generateFunctionName,
    );
    const orchestratorFunctionLogGroup = createLambdaLogGroup(
      "OrchestratorFunctionLogGroup",
      config.orchestratorFunctionName,
    );
    const statusFunctionLogGroup = createLambdaLogGroup(
      "StatusFunctionLogGroup",
      config.statusFunctionName,
    );
    const generateFunction = new lambda.Function(this, "GenerateFunction", {
      functionName: config.generateFunctionName,
      runtime: PYTHON_RUNTIME,
      architecture: lambda.Architecture.X86_64,
      handler: "pipeline.lambdas.generate.handler.handle",
      code: generateCode,
      memorySize: config.generateMemoryMb,
      timeout: cdk.Duration.seconds(config.generateTimeoutSeconds),
      role: generateRole,
      description: "Creates generation jobs and invokes orchestrator asynchronously.",
      environment: {
        JOBS_TABLE_NAME: jobsTable.tableName,
        ORCHESTRATOR_FUNCTION_NAME: config.orchestratorFunctionName,
      },
    });
    generateFunction.node.addDependency(generateFunctionLogGroup);

    const orchestratorFunction = new lambda.Function(this, "OrchestratorFunction", {
      functionName: config.orchestratorFunctionName,
      runtime: PYTHON_RUNTIME,
      architecture: lambda.Architecture.X86_64,
      handler: "pipeline.lambdas.orchestrator.handler.handle",
      code: orchestratorCode,
      memorySize: config.orchestratorMemoryMb,
      timeout: cdk.Duration.seconds(config.orchestratorTimeoutSeconds),
      role: orchestratorRole,
      description: "Runs Director + validator pipeline with RAG grounding.",
      environment: {
        JOBS_TABLE_NAME: jobsTable.tableName,
        BEDROCK_KNOWLEDGE_BASE_ID: "placeholder-set-after-kb",
        BEDROCK_MODEL_ID_DIRECTOR: config.sonnetInferenceProfileId,
        BEDROCK_MODEL_ID_ANIMATOR: config.sonnetInferenceProfileId,
        BEDROCK_MODEL_ID_DRAWING: config.drawingInferenceProfileId,
        BEDROCK_MODEL_ID_RENDERER: config.sonnetInferenceProfileId,
        EPISODES_BUCKET_NAME: episodesBucket.bucketName,
        DRAFTS_PREFIX: config.draftsPrefix,
      },
    });
    orchestratorFunction.node.addDependency(orchestratorFunctionLogGroup);

    const statusFunction = new lambda.Function(this, "StatusFunction", {
      functionName: config.statusFunctionName,
      runtime: PYTHON_RUNTIME,
      architecture: lambda.Architecture.X86_64,
      handler: "pipeline.lambdas.status.handler.handle",
      code: statusCode,
      memorySize: config.statusMemoryMb,
      timeout: cdk.Duration.seconds(config.statusTimeoutSeconds),
      role: statusRole,
      description: "Returns job status from DynamoDB using a single GetItem.",
      environment: {
        JOBS_TABLE_NAME: jobsTable.tableName,
      },
    });
    statusFunction.node.addDependency(statusFunctionLogGroup);

    new lambda.EventInvokeConfig(this, "OrchestratorEventInvokeConfig", {
      function: orchestratorFunction,
      maxEventAge: cdk.Duration.hours(6),
      retryAttempts: config.orchestratorAsyncRetryAttempts,
      onFailure: new lambdaDestinations.SqsDestination(orchestratorDlq),
    });

    const generateFunctionUrl = generateFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,
    });
    const statusFunctionUrl = statusFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,
    });
    const bedrockKnowledgeBaseArnPattern = cdk.Stack.of(this).formatArn({
      service: "bedrock",
      resource: "knowledge-base",
      resourceName: "*",
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
    });

    const bedrockAgentCoreSessionArnPattern = cdk.Stack.of(this).formatArn({
      service: "bedrock-agentcore",
      resource: "session",
      resourceName: "*",
      arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
    });

    generateRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["dynamodb:PutItem", "dynamodb:UpdateItem"],
        resources: [jobsTable.tableArn],
      }),
    );
    generateRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["lambda:InvokeFunction"],
        resources: [orchestratorFunction.functionArn],
      }),
    );

    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [sonnetInferenceProfileArn, drawingInferenceProfileArn],
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [sonnetModelArn],
        conditions: {
          StringLike: {
            "bedrock:InferenceProfileArn": sonnetInferenceProfileArn,
          },
        },
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [drawingModelArn],
        conditions: {
          StringLike: {
            "bedrock:InferenceProfileArn": drawingInferenceProfileArn,
          },
        },
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:RetrieveAndGenerate", "bedrock:Retrieve"],
        resources: [bedrockKnowledgeBaseArnPattern],
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateSession",
          "bedrock-agentcore:GetSession",
          "bedrock-agentcore:UpdateSession",
          "bedrock-agentcore:DeleteSession",
        ],
        resources: [bedrockAgentCoreSessionArnPattern],
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["dynamodb:GetItem", "dynamodb:UpdateItem"],
        resources: [jobsTable.tableArn],
      }),
    );
    orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["s3:PutObject", "s3:DeleteObject"],
        resources: [episodesBucket.arnForObjects(`${config.draftsPrefix}*`)],
      }),
    );

    statusRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["dynamodb:GetItem"],
        resources: [jobsTable.tableArn],
      }),
    );

    const vectorBucket = new s3vectors.CfnVectorBucket(this, "KnowledgeBaseVectorBucket", {
      vectorBucketName: `${this.stackName.toLowerCase()}-kb-vectors`,
    });

    const vectorIndex = new s3vectors.CfnIndex(this, "KnowledgeBaseVectorIndex", {
      indexName: config.kbVectorIndexName,
      dataType: "float32",
      dimension: config.kbEmbeddingDimensions,
      distanceMetric: "cosine",
      vectorBucketArn: vectorBucket.attrVectorBucketArn,
    });
    vectorIndex.node.addDependency(vectorBucket);

    const kbRolePolicy = new iam.Policy(this, "KnowledgeBaseRolePolicy", {
      roles: [kbRole],
      statements: [
        new iam.PolicyStatement({
          actions: ["s3:GetObject"],
          resources: [kbBucket.arnForObjects("*")],
        }),
        new iam.PolicyStatement({
          actions: ["s3:ListBucket"],
          resources: [kbBucket.bucketArn],
        }),
        new iam.PolicyStatement({
          actions: ["bedrock:InvokeModel"],
          resources: [foundationModelArn],
        }),
        new iam.PolicyStatement({
          actions: [
            "s3vectors:QueryVectors",
            "s3vectors:GetVectors",
            "s3vectors:PutVectors",
            "s3vectors:DeleteVectors",
            "s3vectors:GetIndex",
            "s3vectors:GetVectorBucket",
            "s3vectors:ListIndexes",
          ],
          resources: [vectorBucket.attrVectorBucketArn, vectorIndex.attrIndexArn],
        }),
      ],
    });

    const knowledgeBase = new bedrock.CfnKnowledgeBase(this, "KnowledgeBase", {
      name: config.kbName,
      description: "Linions character and narrative grounding knowledge base.",
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: "VECTOR",
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: foundationModelArn,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: config.kbEmbeddingDimensions,
            },
          },
        },
      },
      storageConfiguration: {
        type: "S3_VECTORS",
        s3VectorsConfiguration: {
          vectorBucketArn: vectorBucket.attrVectorBucketArn,
          indexName: config.kbVectorIndexName,
        },
      },
    });
    knowledgeBase.node.addDependency(vectorIndex);
    knowledgeBase.node.addDependency(kbRolePolicy);

    const knowledgeBaseDataSource = new bedrock.CfnDataSource(this, "KnowledgeBaseDataSource", {
      name: config.kbDataSourceName,
      description: "Knowledge base source documents from S3.",
      knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
      dataSourceConfiguration: {
        type: "S3",
        s3Configuration: {
          bucketArn: kbBucket.bucketArn,
        },
      },
    });
    knowledgeBaseDataSource.node.addDependency(knowledgeBase);

    orchestratorFunction.addEnvironment(
      "BEDROCK_KNOWLEDGE_BASE_ID",
      knowledgeBase.attrKnowledgeBaseId,
    );

    const episodesCachePolicy = new cloudfront.CachePolicy(this, "EpisodesCachePolicy", {
      defaultTtl: cdk.Duration.seconds(config.episodeCacheTtlSeconds),
      minTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.seconds(config.episodeCacheTtlSeconds),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.none(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
      enableAcceptEncodingBrotli: true,
      enableAcceptEncodingGzip: true,
    });

    const staticAssetCachePolicy = new cloudfront.CachePolicy(this, "StaticAssetCachePolicy", {
      defaultTtl: cdk.Duration.seconds(config.staticAssetCacheTtlSeconds),
      minTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.seconds(config.staticAssetCacheTtlSeconds),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.none(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
    });

    const svgAssetCachePolicy = new cloudfront.CachePolicy(this, "SvgAssetCachePolicy", {
      defaultTtl: cdk.Duration.seconds(config.svgAssetCacheTtlSeconds),
      minTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.seconds(config.svgAssetCacheTtlSeconds),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.none(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
      enableAcceptEncodingBrotli: true,
      enableAcceptEncodingGzip: true,
    });

    const indexJsonCachePolicy = new cloudfront.CachePolicy(this, "IndexJsonCachePolicy", {
      defaultTtl: cdk.Duration.seconds(config.indexJsonCacheTtlSeconds),
      minTtl: cdk.Duration.seconds(0),
      maxTtl: cdk.Duration.seconds(config.indexJsonCacheTtlSeconds),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.none(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
    });

    const indexHtmlCachePolicy = new cloudfront.CachePolicy(this, "IndexHtmlCachePolicy", {
      defaultTtl: cdk.Duration.seconds(config.indexHtmlCacheTtlSeconds),
      minTtl: cdk.Duration.seconds(config.indexHtmlCacheTtlSeconds),
      maxTtl: cdk.Duration.seconds(config.indexHtmlCacheTtlSeconds),
      cookieBehavior: cloudfront.CacheCookieBehavior.none(),
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.none(),
      headerBehavior: cloudfront.CacheHeaderBehavior.none(),
    });

    const sharedSecurityHeadersBehavior = {
      contentTypeOptions: { override: true },
      frameOptions: {
        frameOption: cloudfront.HeadersFrameOption.DENY,
        override: true,
      },
      contentSecurityPolicy: {
        contentSecurityPolicy: [
          "default-src 'self'",
          "script-src 'self' static.cloudflareinsights.com",
          "style-src 'self'",
          "font-src 'self' data:",
          "img-src 'self' data:",
          "connect-src 'self' cloudflareinsights.com",
          "object-src 'none'",
          "base-uri 'self'",
          "frame-ancestors 'none'",
        ].join("; "),
        override: true,
      },
    };

    const securityHeadersPolicy = new cloudfront.ResponseHeadersPolicy(this, "SecurityHeadersPolicy", {
      securityHeadersBehavior: sharedSecurityHeadersBehavior,
    });

    const noCacheResponseHeadersPolicy = new cloudfront.ResponseHeadersPolicy(
      this,
      "NoCacheResponseHeadersPolicy",
      {
        securityHeadersBehavior: sharedSecurityHeadersBehavior,
        customHeadersBehavior: {
          customHeaders: [
            {
              header: "Cache-Control",
              value: "no-store, max-age=0, must-revalidate",
              override: true,
            },
          ],
        },
      },
    );

    const originAccessControl = new cloudfront.CfnOriginAccessControl(this, "EpisodesOac", {
      originAccessControlConfig: {
        name: `${this.stackName}-episodes-oac`,
        originAccessControlOriginType: "s3",
        signingBehavior: "always",
        signingProtocol: "sigv4",
      },
    });

    const spaRewriteFunction = new cloudfront.CfnFunction(this, "SpaRewriteFunction", {
      name: `${this.stackName.toLowerCase()}-spa-rewrite`,
      autoPublish: true,
      functionConfig: {
        comment: "Rewrite public viewer story routes to index.html while preserving assets.",
        runtime: "cloudfront-js-2.0",
      },
      functionCode: `
function handler(event) {
  var request = event.request;
  var uri = request.uri || "/";

  if (uri === "/" || uri === "/index.html") {
    return request;
  }

  if (uri.startsWith("/episodes/")) {
    return request;
  }

  if (/\\.[A-Za-z0-9]+$/.test(uri)) {
    return request;
  }

  request.uri = "/index.html";
  return request;
}
      `.trim(),
    });

    const cloudFrontDistribution = new cloudfront.CfnDistribution(this, "Distribution", {
      distributionConfig: {
        enabled: true,
        defaultRootObject: "index.html",
        httpVersion: "http2",
        priceClass: "PriceClass_100",
        viewerCertificate: {
          minimumProtocolVersion: "TLSv1.2_2021",
          cloudFrontDefaultCertificate: true,
        },
        origins: [
          {
            id: "EpisodesS3Origin",
            domainName: episodesBucket.bucketRegionalDomainName,
            s3OriginConfig: {},
            originAccessControlId: originAccessControl.attrId,
          },
        ],
        defaultCacheBehavior: {
          targetOriginId: "EpisodesS3Origin",
          viewerProtocolPolicy: "redirect-to-https",
          allowedMethods: ["GET", "HEAD", "OPTIONS"],
          cachedMethods: ["GET", "HEAD", "OPTIONS"],
          compress: true,
          cachePolicyId: indexHtmlCachePolicy.cachePolicyId,
          responseHeadersPolicyId: noCacheResponseHeadersPolicy.responseHeadersPolicyId,
          functionAssociations: [
            {
              eventType: "viewer-request",
              functionArn: spaRewriteFunction.attrFunctionMetadataFunctionArn,
            },
          ],
        },
        cacheBehaviors: [
          {
            pathPattern: "episodes/index.json",
            targetOriginId: "EpisodesS3Origin",
            viewerProtocolPolicy: "redirect-to-https",
            allowedMethods: ["GET", "HEAD", "OPTIONS"],
            cachedMethods: ["GET", "HEAD", "OPTIONS"],
            compress: true,
            cachePolicyId: indexJsonCachePolicy.cachePolicyId,
            responseHeadersPolicyId: noCacheResponseHeadersPolicy.responseHeadersPolicyId,
          },
          {
            pathPattern: "episodes/*",
            targetOriginId: "EpisodesS3Origin",
            viewerProtocolPolicy: "redirect-to-https",
            allowedMethods: ["GET", "HEAD", "OPTIONS"],
            cachedMethods: ["GET", "HEAD", "OPTIONS"],
            compress: true,
            cachePolicyId: episodesCachePolicy.cachePolicyId,
            responseHeadersPolicyId: securityHeadersPolicy.responseHeadersPolicyId,
          },
          {
            pathPattern: "*.js",
            targetOriginId: "EpisodesS3Origin",
            viewerProtocolPolicy: "redirect-to-https",
            allowedMethods: ["GET", "HEAD", "OPTIONS"],
            cachedMethods: ["GET", "HEAD", "OPTIONS"],
            compress: true,
            cachePolicyId: staticAssetCachePolicy.cachePolicyId,
            responseHeadersPolicyId: noCacheResponseHeadersPolicy.responseHeadersPolicyId,
          },
          {
            pathPattern: "*.css",
            targetOriginId: "EpisodesS3Origin",
            viewerProtocolPolicy: "redirect-to-https",
            allowedMethods: ["GET", "HEAD", "OPTIONS"],
            cachedMethods: ["GET", "HEAD", "OPTIONS"],
            compress: true,
            cachePolicyId: staticAssetCachePolicy.cachePolicyId,
            responseHeadersPolicyId: noCacheResponseHeadersPolicy.responseHeadersPolicyId,
          },
          {
            pathPattern: "*.svg",
            targetOriginId: "EpisodesS3Origin",
            viewerProtocolPolicy: "redirect-to-https",
            allowedMethods: ["GET", "HEAD", "OPTIONS"],
            cachedMethods: ["GET", "HEAD", "OPTIONS"],
            compress: true,
            cachePolicyId: svgAssetCachePolicy.cachePolicyId,
            responseHeadersPolicyId: securityHeadersPolicy.responseHeadersPolicyId,
          },
        ],
      },
    });

    cloudFrontDistribution.node.addDependency(originAccessControl);
    cloudFrontDistribution.node.addDependency(spaRewriteFunction);

    episodesBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "AllowCloudFrontReadWithOac",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("cloudfront.amazonaws.com")],
        actions: ["s3:GetObject"],
        resources: [episodesBucket.arnForObjects("*")],
        conditions: {
          StringEquals: {
            "AWS:SourceArn": cdk.Stack.of(this).formatArn({
              service: "cloudfront",
              region: "",
              account: account,
              resource: "distribution",
              resourceName: cloudFrontDistribution.ref,
              arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
            }),
          },
        },
      }),
    );

    episodesBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "DenyDirectObjectReadOutsideDraftsWithoutCloudFrontSourceArn",
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:GetObject"],
        notResources: [episodesBucket.arnForObjects(`${config.draftsPrefix}*`)],
        conditions: {
          StringNotEquals: {
            "AWS:SourceArn": cdk.Stack.of(this).formatArn({
              service: "cloudfront",
              region: "",
              account: account,
              resource: "distribution",
              resourceName: cloudFrontDistribution.ref,
              arnFormat: cdk.ArnFormat.SLASH_RESOURCE_NAME,
            }),
          },
        },
      }),
    );

    new s3deploy.BucketDeployment(this, "FrontendDeployment", {
      sources: [s3deploy.Source.asset(path.join(projectRoot, "frontend/dist-public"))],
      destinationBucket: episodesBucket,
      prune: false,
    });

    new s3deploy.BucketDeployment(this, "EpisodesDeployment", {
      sources: [s3deploy.Source.asset(path.join(projectRoot, "episodes"))],
      destinationBucket: episodesBucket,
      destinationKeyPrefix: "episodes",
      prune: true,
    });

    new s3deploy.BucketDeployment(this, "KnowledgeBaseDeployment", {
      sources: [s3deploy.Source.asset(path.join(projectRoot, "knowledge-base"))],
      destinationBucket: kbBucket,
      prune: false,
    });

    new cdk.CfnOutput(this, "GenerateFunctionUrl", {
      value: generateFunctionUrl.url,
      description: "Function URL for linions-generate endpoint.",
    });

    new cdk.CfnOutput(this, "StatusFunctionUrl", {
      value: statusFunctionUrl.url,
      description: "Function URL for linions-status endpoint.",
    });

    new cdk.CfnOutput(this, "CloudFrontDomain", {
      value: `https://${cloudFrontDistribution.attrDomainName}`,
      description: "CloudFront distribution domain for frontend and episodes.",
    });

    new cdk.CfnOutput(this, "EpisodesBucketName", {
      value: episodesBucket.bucketName,
      description: "S3 bucket name for published episodes.",
    });

    new cdk.CfnOutput(this, "KnowledgeBaseBucketName", {
      value: kbBucket.bucketName,
      description: "S3 bucket name for Bedrock Knowledge Base source documents.",
    });

    new cdk.CfnOutput(this, "KnowledgeBaseId", {
      value: knowledgeBase.attrKnowledgeBaseId,
      description: "Bedrock Knowledge Base identifier used by Director RAG calls.",
    });
  }
}
