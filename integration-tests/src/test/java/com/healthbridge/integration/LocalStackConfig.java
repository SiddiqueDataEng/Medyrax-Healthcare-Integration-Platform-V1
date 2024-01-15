package com.Medyrax.integration;

import org.testcontainers.containers.localstack.LocalStackContainer;
import org.testcontainers.utility.DockerImageName;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.sqs.SqsClient;

/**
 * Shared LocalStack configuration for Medyrax™ integration tests.
 *
 * <p>Provides a singleton LocalStack container and pre-configured AWS SDK v2
 * clients pointing to the LocalStack endpoint. Integration tests extend or
 * compose this class.
 *
 * <p>Testing strategy reference:
 * "Integration tests use LocalStack for AWS service mocks (SQS, S3, DynamoDB,
 * EventBridge) and a mock HealthLake endpoint."
 */
public class LocalStackConfig {

    /** Pinned LocalStack image version for reproducibility. */
    public static final DockerImageName LOCALSTACK_IMAGE =
            DockerImageName.parse("localstack/localstack:3.4.0");

    /**
     * Returns an AWS basic credentials provider for LocalStack
     * (any non-empty string works as credentials for LocalStack).
     */
    public static StaticCredentialsProvider localStackCredentials() {
        return StaticCredentialsProvider.create(
                AwsBasicCredentials.create("test", "test")
        );
    }

    /**
     * Creates a DynamoDB client connected to a running LocalStack container.
     *
     * @param container a started {@link LocalStackContainer}
     */
    public static DynamoDbClient dynamoDbClient(LocalStackContainer container) {
        return DynamoDbClient.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.DYNAMODB))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    /**
     * Creates an S3 client connected to a running LocalStack container.
     *
     * @param container a started {@link LocalStackContainer}
     */
    public static S3Client s3Client(LocalStackContainer container) {
        return S3Client.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.S3))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }

    /**
     * Creates an SQS client connected to a running LocalStack container.
     *
     * @param container a started {@link LocalStackContainer}
     */
    public static SqsClient sqsClient(LocalStackContainer container) {
        return SqsClient.builder()
                .endpointOverride(container.getEndpointOverride(LocalStackContainer.Service.SQS))
                .credentialsProvider(localStackCredentials())
                .region(Region.US_EAST_1)
                .build();
    }
}
