"""CDK assertions for Phase 2 infrastructure security properties."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_DIR = REPO_ROOT / "infra"
_TEMPLATE_CACHE: dict[str, Any] | None = None


def _load_template_from_cdk_out() -> dict[str, Any] | None:
    """Load synthesized template from cdk.out when already available."""
    template_path = REPO_ROOT / "cdk.out" / "LinionsStack.template.json"
    if not template_path.exists():
        return None
    return json.loads(template_path.read_text(encoding="utf-8"))


def _run_cdk_synth() -> dict[str, Any]:
    """Load stack template with optional synth.

    Default behavior is fast: reuse infra/cdk.out template when present.
    Set LINIONS_FORCE_CDK_SYNTH=1 to force an explicit synth even when a cached
    template already exists.
    """
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    if os.getenv("LINIONS_FORCE_CDK_SYNTH", "0") != "1":
        cached_template = _load_template_from_cdk_out()
        if cached_template is not None:
            _TEMPLATE_CACHE = cached_template
            return _TEMPLATE_CACHE

        pytest.fail(
            "CDK security assertion tests require a synthesized template.\n"
            "Options:\n"
            "  1. Run `cdk synth` from the repo root first, then re-run pytest.\n"
            "  2. Set LINIONS_FORCE_CDK_SYNTH=1 to trigger synth automatically.\n"
            "STANDARDS.md §6.3: these tests must never be silently skipped."
        )

    with tempfile.TemporaryDirectory(prefix="linions-cdk-synth-") as temp_out:
        subprocess.run(
            [
                "cdk",
                "synth",
                "--quiet",
                "--output",
                temp_out,
            ],
            check=True,
            cwd=REPO_ROOT,
            timeout=600,
        )
        template_path = Path(temp_out) / "LinionsStack.template.json"
        _TEMPLATE_CACHE = json.loads(template_path.read_text(encoding="utf-8"))
        return _TEMPLATE_CACHE


def _resources_by_type(template: dict[str, Any], resource_type: str) -> dict[str, dict[str, Any]]:
    """Return template resources filtered by CloudFormation type."""
    resources = template.get("Resources", {})
    return {
        logical_id: resource
        for logical_id, resource in resources.items()
        if resource.get("Type") == resource_type
    }


def test_s3_buckets_use_block_public_access() -> None:
    """Assert every S3 bucket has full public access block enabled."""
    template = _run_cdk_synth()
    s3_buckets = _resources_by_type(template, "AWS::S3::Bucket")
    assert s3_buckets, "Expected at least one S3 bucket in stack template"

    for bucket in s3_buckets.values():
        config = bucket["Properties"].get("PublicAccessBlockConfiguration", {})
        assert config.get("BlockPublicAcls") is True
        assert config.get("IgnorePublicAcls") is True
        assert config.get("BlockPublicPolicy") is True
        assert config.get("RestrictPublicBuckets") is True


def test_lambda_function_urls_require_aws_iam_auth() -> None:
    """Assert Function URLs are IAM protected."""
    template = _run_cdk_synth()
    function_urls = _resources_by_type(template, "AWS::Lambda::Url")
    assert function_urls, "Expected Lambda Function URL resources"

    for function_url in function_urls.values():
        assert function_url["Properties"].get("AuthType") == "AWS_IAM"


def test_no_iam_policy_statement_uses_wildcard_resource() -> None:
    """Assert IAM policy statements do not grant wildcard resources."""
    template = _run_cdk_synth()
    iam_policies = _resources_by_type(template, "AWS::IAM::Policy")

    for policy in iam_policies.values():
        statements = policy["Properties"]["PolicyDocument"]["Statement"]
        if isinstance(statements, dict):
            statements = [statements]

        for statement in statements:
            resources = statement.get("Resource")
            if resources is None:
                continue

            if isinstance(resources, list):
                assert "*" not in resources
            else:
                assert resources != "*"


def test_cloudfront_distribution_uses_modern_tls() -> None:
    """Assert CloudFront minimum protocol version is TLSv1.2_2021."""
    template = _run_cdk_synth()
    distributions = _resources_by_type(template, "AWS::CloudFront::Distribution")
    assert distributions, "Expected CloudFront distribution resource"

    for distribution in distributions.values():
        cert_config = distribution["Properties"]["DistributionConfig"]["ViewerCertificate"]
        assert cert_config.get("MinimumProtocolVersion") == "TLSv1.2_2021"


def test_dynamodb_table_has_ttl_enabled() -> None:
    """Assert DynamoDB table includes ttl attribute configuration."""
    template = _run_cdk_synth()
    tables = _resources_by_type(template, "AWS::DynamoDB::Table")
    assert tables, "Expected DynamoDB table resource"

    for table in tables.values():
        ttl_spec = table["Properties"].get("TimeToLiveSpecification", {})
        assert ttl_spec.get("AttributeName") == "ttl"
        assert ttl_spec.get("Enabled") is True


def test_lambda_log_retention_is_managed_at_14_days() -> None:
    """Assert Lambda log groups are stack-owned with 14-day retention."""
    template = _run_cdk_synth()
    explicit_log_groups = _resources_by_type(template, "AWS::Logs::LogGroup")
    lambda_named_log_groups = [
        resource
        for resource in explicit_log_groups.values()
        if str(resource.get("Properties", {}).get("LogGroupName", "")).startswith("/aws/lambda/")
    ]
    assert len(lambda_named_log_groups) >= 3

    for resource in lambda_named_log_groups:
        assert resource["Properties"].get("RetentionInDays") == 14


def test_orchestrator_has_dlq_destination() -> None:
    """Assert orchestrator async invoke config sends failures to SQS DLQ."""
    template = _run_cdk_synth()
    event_invoke_configs = _resources_by_type(template, "AWS::Lambda::EventInvokeConfig")
    assert event_invoke_configs, "Expected Lambda EventInvokeConfig resource"

    for invoke_config in event_invoke_configs.values():
        destination_config = invoke_config["Properties"].get("DestinationConfig", {})
        failure_destination = destination_config.get("OnFailure", {}).get("Destination")
        if failure_destination:
            return

    raise AssertionError(
        "Expected at least one Lambda EventInvokeConfig with OnFailure destination"
    )


def test_orchestrator_async_retry_attempts_are_configurable_and_default_disabled() -> None:
    """Assert async retries are config-driven and currently default to disabled."""
    config_source = (REPO_ROOT / "infra" / "config.ts").read_text(encoding="utf-8")
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")
    template = _run_cdk_synth()
    event_invoke_configs = _resources_by_type(template, "AWS::Lambda::EventInvokeConfig")
    assert event_invoke_configs, "Expected Lambda EventInvokeConfig resource"

    assert "orchestratorAsyncRetryAttempts: 0" in config_source
    assert "retryAttempts: config.orchestratorAsyncRetryAttempts" in stack_source

    for invoke_config in event_invoke_configs.values():
        maximum_retry_attempts = invoke_config["Properties"].get("MaximumRetryAttempts")
        if maximum_retry_attempts is not None:
            assert maximum_retry_attempts == 0
            return

    raise AssertionError("Expected Lambda EventInvokeConfig MaximumRetryAttempts to equal 0")


def test_python_lambda_handlers_use_pipeline_module_paths() -> None:
    """Assert Python Lambda handlers point at package-qualified pipeline modules.

    This guards against runtime import failures like
    ``Runtime.ImportModuleError: No module named 'pipeline'`` when handler paths
    are configured as top-level modules while code imports use ``from pipeline``.
    """
    template = _run_cdk_synth()
    lambda_functions = _resources_by_type(template, "AWS::Lambda::Function")
    assert lambda_functions, "Expected Lambda function resources"

    expected_handlers = {
        "pipeline.lambdas.generate.handler.handle",
        "pipeline.lambdas.status.handler.handle",
        "pipeline.lambdas.orchestrator.handler.handle",
    }

    handlers = {
        resource.get("Properties", {}).get("Handler")
        for resource in lambda_functions.values()
        if resource.get("Properties", {}).get("Runtime") == "python3.11"
    }

    for handler in expected_handlers:
        assert handler in handlers


def test_infra_stack_bundles_only_non_runtime_python_dependencies() -> None:
    """Assert bundling reuses Lambda's AWS SDK and only installs remaining deps."""
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "pipeline/lambdas/generate/requirements.txt" in stack_source
    assert "pipeline/lambdas/status/requirements.txt" in stack_source
    assert "pipeline/lambdas/orchestrator/requirements.txt" in stack_source
    assert '"**/__pycache__/**"' in stack_source
    assert '"**/*.pyc"' in stack_source
    assert "requirements.lock" in stack_source
    assert "runtime-requirements.txt" in stack_source
    assert "using AWS Lambda runtime boto3" in stack_source
    assert "pip install --prefer-binary --no-compile" in stack_source
    assert 'find /asset-output -mindepth 1 -maxdepth 1 -type d' in stack_source
    assert '-name "*.dist-info"' in stack_source
    assert '-name "*.egg-info"' in stack_source
    assert "-exec rm -rf {} +" in stack_source
    assert "buildAssetCopyCommand" in stack_source
    assert "boto3([[:space:]]|[<>=!~].*)?$" in stack_source
    assert (
        'copyPaths: [...lambdaPackagePaths, ...sharedRuntimePaths, "pipeline/lambdas/generate"]'
        in stack_source
    )
    assert '"frontend/public/linai-template.svg"' in stack_source
    assert '"frontend/public/obstacles"' in stack_source
    assert '"frontend/public/backgrounds"' in stack_source


def test_infra_stack_emits_bundle_timings_in_cdk_logs() -> None:
    """Assert bundling logs include timing markers for source copy and deps."""
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "bundle_start=$SECONDS" in stack_source
    assert "copy_start=$SECONDS" in stack_source
    assert "deps_start=$SECONDS" in stack_source
    assert "copied source files in $((SECONDS - copy_start))s" in stack_source
    assert "dependency step finished in $((SECONDS - deps_start))s" in stack_source
    assert "total bundle time $((SECONDS - bundle_start))s" in stack_source


def test_infra_stack_routes_agent_calls_through_explicit_model_profiles() -> None:
    """Assert orchestrator agents use explicit, intentional Bedrock model IDs."""
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert 'resource: "inference-profile"' in stack_source
    assert "config.sonnetInferenceProfileId" in stack_source
    assert "config.drawingInferenceProfileId" in stack_source
    assert "BEDROCK_MODEL_ID_DIRECTOR: config.sonnetInferenceProfileId" in stack_source
    assert "BEDROCK_MODEL_ID_ANIMATOR: config.sonnetInferenceProfileId" in stack_source
    assert "BEDROCK_MODEL_ID_DRAWING: config.drawingInferenceProfileId" in stack_source
    assert "BEDROCK_MODEL_ID_RENDERER: config.sonnetInferenceProfileId" in stack_source
    assert '"bedrock:InferenceProfileArn": sonnetInferenceProfileArn' in stack_source


def test_episodes_bucket_direct_read_deny_excludes_drafts() -> None:
    """Assert direct-read deny policy keeps draft objects accessible to the local proxy."""
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "DenyDirectObjectReadOutsideDraftsWithoutCloudFrontSourceArn" in stack_source
    assert "notResources: [episodesBucket.arnForObjects(`${config.draftsPrefix}*`)]" in stack_source
    assert '"bedrock:InferenceProfileArn": drawingInferenceProfileArn' in stack_source
    assert "resources: [drawingModelArn]" in stack_source
    assert "CfnApplicationInferenceProfile" not in stack_source


def test_cloudfront_csp_allows_self_and_data_fonts() -> None:
    """Assert CloudFront CSP declares an explicit font-src policy."""
    template = _run_cdk_synth()
    policies = _resources_by_type(template, "AWS::CloudFront::ResponseHeadersPolicy")
    assert policies, "Expected CloudFront response headers policy"

    for policy in policies.values():
        csp = policy["Properties"]["ResponseHeadersPolicyConfig"]["SecurityHeadersConfig"][
            "ContentSecurityPolicy"
        ]["ContentSecurityPolicy"]
        assert "font-src 'self' data:" in csp
        assert "img-src 'self' data:" in csp
        return

    raise AssertionError("Expected a CloudFront response headers policy with CSP")


def test_static_asset_cache_ttl_is_zero_to_avoid_stale_frontend_modules() -> None:
    """Assert JS/CSS responses stay fresh across deploys."""
    config_source = (REPO_ROOT / "infra" / "config.ts").read_text(encoding="utf-8")
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "staticAssetCacheTtlSeconds: 0" in config_source
    assert "NoCacheResponseHeadersPolicy" in stack_source
    assert 'pathPattern: "*.js"' in stack_source
    assert 'pathPattern: "*.css"' in stack_source
    assert 'header: "Cache-Control"' in stack_source
    assert 'value: "no-store, max-age=0, must-revalidate"' in stack_source
    assert (
        "responseHeadersPolicyId: "
        "noCacheResponseHeadersPolicy.responseHeadersPolicyId"
    ) in stack_source


def test_svg_assets_keep_a_dedicated_cache_policy() -> None:
    """Assert published SVG assets stay cached independently from JS/CSS."""
    config_source = (REPO_ROOT / "infra" / "config.ts").read_text(encoding="utf-8")
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "svgAssetCacheTtlSeconds: 259200" in config_source
    assert "SvgAssetCachePolicy" in stack_source
    assert 'pathPattern: "*.svg"' in stack_source
    assert "cachePolicyId: svgAssetCachePolicy.cachePolicyId" in stack_source


def test_index_json_cache_ttl_is_zero() -> None:
    """Assert episodes/index.json uses an always-fresh cache policy."""
    config_source = (REPO_ROOT / "infra" / "config.ts").read_text(encoding="utf-8")
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "indexJsonCacheTtlSeconds: 0" in config_source
    assert 'pathPattern: "episodes/index.json"' in stack_source
    assert "IndexJsonCachePolicy" in stack_source


def test_infra_stack_sanitises_lock_file_before_using_it_as_pip_constraints() -> None:
    """Assert Lambda bundling strips extras from lock lines before ``-c`` use.

    pip rejects constraints entries like ``coverage[toml]==...`` and
    ``pyjwt[crypto]==...`` with ``Constraints cannot have extras``. The bundling
    command must normalise those lines before passing the lock file as
    constraints for runtime-only installs.
    """
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert "requirements.lambda.constraints.txt" in stack_source
    assert "sed -E" in stack_source
    assert "\\\\[[^]]+\\\\]" in stack_source


def test_infra_stack_uses_x86_64_python_bundling_for_binary_dependencies() -> None:
    """Assert bundling/runtime architecture avoids pydantic_core binary mismatch.

    pydantic v2 ships a compiled extension (``pydantic_core``). If dependencies
    are bundled for ARM64 but Lambda runs x86_64 (or vice versa), imports fail
    with ``No module named 'pydantic_core._pydantic_core'``.
    """
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert 'platform: "linux/amd64"' in stack_source
    assert "architecture: lambda.Architecture.X86_64" in stack_source


def test_infra_stack_configures_writable_pip_cache_for_bundling_speed() -> None:
    """Assert bundling sets pip cache env/volume to avoid repeated downloads.

    This guards against warnings like
    ``The directory '/.cache/pip' ... is not writable`` and reduces local
    CDK synth/deploy time by reusing downloaded wheels.
    """
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert 'PIP_CACHE_DIR: "/tmp/pip-cache"' in stack_source
    assert 'HOME: "/tmp"' in stack_source
    assert 'containerPath: "/tmp/pip-cache"' in stack_source


def test_infra_stack_sets_root_bundling_user_to_reduce_uid_lookup_noise() -> None:
    """Assert bundling runs as root to avoid unresolved host UID warnings."""
    stack_source = (REPO_ROOT / "infra" / "lib" / "linions-stack.ts").read_text(encoding="utf-8")

    assert 'user: "root"' in stack_source
