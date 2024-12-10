package com.healthbridge.integration;

import org.testcontainers.containers.localstack.LocalStackContainer;
import org.testcontainers.utility.DockerImageName;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.sqs.SqsClient;

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Shared LocalStack configuration for Medyrax integration tests (task 23.1).
 *
 * Provides a singleton LocalStack container and pre-configured AWS SDK v2
 * clients pointing to the LocalStack endpoint.
 *
 * Also provides in-memory RBAC permission fixtures that mirror the
 * DynamoDB mdx-rbac-permissions table (for RBAC tests in task 23.1, checkpoint 15).
 */
public class LocalStackConfig {

    public static final DockerImageName LOCALSTACK_IMAGE =
            DockerImageName.parse("localstack/localstack:3.4.0");

    /** Default LocalStack endpoint for tests running without a container (mock endpoint). */
    private static final String DEFAULT_ENDPOINT = "http://localhost:4566";

    public static StaticCredentialsProvider localStackCredentials() {
        return StaticCredentialsProvider.create(
                AwsBasicCredentials.create("test", "test")
        );
    }

    // ── Client factory methods (container-based) ──────────────────────────

    public static DynamoDbClient dynamoDbClient(LocalStackContainer container) {
        return DynamoDbClient.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.DYNAMODB))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    public static S3Client s3Client(LocalStackContainer container) {
        return S3Client.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.S3))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    public static SqsClient sqsClient(LocalStackContainer container) {
        return SqsClient.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.SQS))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    // ── Client factory methods (no container — default endpoint) ─────────
    // Used in tests that mock the endpoint themselves (e.g. unit-style integration tests).

    public static DynamoDbClient dynamoDbClient() {
        return DynamoDbClient.builder()
                .endpointOverride(URI.create(DEFAULT_ENDPOINT))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    public static S3Client s3Client() {
        return S3Client.builder()
                .endpointOverride(URI.create(DEFAULT_ENDPOINT))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    public static SqsClient sqsClient() {
        return SqsClient.builder()
                .endpointOverride(URI.create(DEFAULT_ENDPOINT))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    // ── In-memory RBAC permission fixtures (mirrors mdx-rbac-permissions DynamoDB table) ──

    private static final Map<String, List<String>> RBAC_PERMISSIONS = Map.of(
        "Platform_Admin", List.of("*"),
        "Organization_Admin", List.of(
            "fhir:*:read", "fhir:*:create", "fhir:*:update",
            "tenant:*:read", "tenant:*:update"
        ),
        "Clinical_User", List.of(
            "fhir:Patient:read", "fhir:Encounter:read", "fhir:Observation:read",
            "fhir:Observation:create", "fhir:Condition:read",
            "fhir:MedicationRequest:read", "fhir:DiagnosticReport:read"
        ),
        "Integration_Service", List.of(
            "fhir:*:read", "fhir:*:create", "fhir:*:update",
            "healthlake:*:*", "integration_bus:*:publish"
        ),
        "Audit_Reviewer", List.of("audit:*:read", "compliance:*:read")
    );

    /**
     * Return the set of permissions for a given RBAC role.
     * Mirrors the DynamoDB query logic without requiring a live connection.
     *
     * @param roleName One of: Platform_Admin, Organization_Admin, Clinical_User,
     *                 Integration_Service, Audit_Reviewer
     */
    public static List<String> getRbacPermissions(String roleName) {
        return RBAC_PERMISSIONS.getOrDefault(roleName, List.of());
    }
}
