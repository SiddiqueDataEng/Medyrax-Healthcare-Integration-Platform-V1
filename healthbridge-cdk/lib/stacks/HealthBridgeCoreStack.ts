import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '../types';
import { MedyraxSecurityStack } from './MedyraxSecurityStack';
import { MedyraxDataStack } from './MedyraxDataStack';

/**
 * Props for the Core Stack.
 */
export interface MedyraxCoreStackProps extends MedyraxStackProps {
  securityStack: MedyraxSecurityStack;
  dataStack: MedyraxDataStack;
}

/**
 * Medyrax™ Core Stack
 *
 * Provisions the API Gateway, Cognito User Pool, and the access logging
 * infrastructure. Lambda functions, SQS queues, and EventBridge buses are
 * provisioned here at the platform level. Per-org resources (queues, buses)
 * are provisioned by the Tenant Stack during onboarding.
 *
 * Individual Lambda function definitions are added in subsequent tasks
 * (tasks 5–20). This stack provides the CDK scaffolding so those tasks
 * can attach to the existing API Gateway and Cognito pool.
 *
 * Requirements 6.1 – 6.8 (API Gateway layer)
 * Requirements 7.7 (Cognito session management)
 */
export class MedyraxCoreStack extends cdk.Stack {

  /** The shared Cognito User Pool for OAuth 2.0 / JWT enforcement. */
  public readonly userPool: cognito.UserPool;

  /** The Cognito User Pool ARN — used to create JWT authorizer. */
  public readonly userPoolArn: string;

  /** The REST API Gateway instance. */
  public readonly api: apigateway.RestApi;

  /** The API Gateway ID — used by per-Lambda task stacks to add routes. */
  public readonly apiId: string;

  /** CloudWatch Logs group for API Gateway access logging. */
  public readonly apiAccessLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: MedyraxCoreStackProps) {
    super(scope, id, props);

    const { envName, envConfig, securityStack } = props;

    // ── Cognito User Pool ────────────────────────────────────────────────────
    // Requirement 7.7: access token expiry = 15 minutes (configurable per-org)
    // Requirement 6.2: OAuth 2.0 JWT enforcement on all endpoints
    const cognitoAccessTokenExpiry = envConfig.cognitoAccessTokenExpiryMinutes ?? 15;

    this.userPool = new cognito.UserPool(this, 'MedyraxUserPool', {
      userPoolName:    `hb-user-pool-${envName}`,
      selfSignUpEnabled: false,
      signInAliases:   { email: true, username: true },
      standardAttributes: {
        email:    { required: true, mutable: true },
        fullname: { required: false, mutable: true },
      },
      customAttributes: {
        orgId: new cognito.StringAttribute({ mutable: false }),
        role:  new cognito.StringAttribute({ mutable: true }),
      },
      passwordPolicy: {
        minLength:        14,
        requireUppercase: true,
        requireLowercase: true,
        requireDigits:    true,
        requireSymbols:   true,
        tempPasswordValidity: cdk.Duration.days(1),
      },
      accountRecovery:  cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy:    envName === 'prod'
                          ? cdk.RemovalPolicy.RETAIN
                          : cdk.RemovalPolicy.DESTROY,
    });

    // Platform app client — used by the API Gateway JWT authorizer
    this.userPool.addClient('PlatformAppClient', {
      userPoolClientName: `hb-platform-client-${envName}`,
      authFlows: {
        userPassword:   false,
        userSrp:        true,
        adminUserPassword: true,
      },
      oAuth: {
        flows:  { clientCredentials: true, authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
      },
      accessTokenValidity:  cdk.Duration.minutes(cognitoAccessTokenExpiry),
      idTokenValidity:      cdk.Duration.minutes(cognitoAccessTokenExpiry),
      refreshTokenValidity: cdk.Duration.days(30),
      preventUserExistenceErrors: true,
    });

    this.userPoolArn = this.userPool.userPoolArn;

    // ── API Gateway Access Log Group ─────────────────────────────────────────
    this.apiAccessLogGroup = new logs.LogGroup(this, 'ApiAccessLogGroup', {
      logGroupName: `/Medyrax/${envName}/api-access`,
      retention:    logs.RetentionDays.THREE_MONTHS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── REST API Gateway ─────────────────────────────────────────────────────
    // Requirement 6.1: FHIR R4 base URL conforming to HL7 FHIR RESTful spec
    // Requirement 6.5: URL path prefix versioning (/v1/, /v2/)
    // Requirement 6.6: CloudWatch Logs access logging within 1 second
    this.api = new apigateway.RestApi(this, 'MedyraxApi', {
      restApiName: `Medyrax-api-${envName}`,
      description: 'Medyrax™ FHIR R4 and REST API',
      deployOptions: {
        stageName:           'v1',
        tracingEnabled:      envConfig.enableXRay !== false,   // X-Ray (Requirement 14.4)
        loggingLevel:        apigateway.MethodLoggingLevel.INFO,
        accessLogDestination: new apigateway.LogGroupLogDestination(this.apiAccessLogGroup),
        accessLogFormat:     apigateway.AccessLogFormat.jsonWithStandardFields({
          caller:      true,
          httpMethod:  true,
          ip:          true,
          protocol:    true,
          requestTime: true,
          resourcePath: true,
          responseLength: true,
          status:      true,
          user:        true,
        }),
        throttlingRateLimit:  1000,   // Base throttle
        throttlingBurstLimit: 2000,
        metricsEnabled:       true,
      },
      defaultCorsPreflightOptions: {
        // Requirement 6.8: CORS for browser-based FHIR clients
        allowOrigins: apigateway.Cors.ALL_ORIGINS,  // Narrowed per-org at usage plan level
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          'Content-Type',
          'Authorization',
          'X-Amz-Date',
          'X-Api-Key',
          'X-Amz-Security-Token',
          'X-PHI-Masking',
          'Accept-Encoding',
        ],
        maxAge: cdk.Duration.days(1),
      },
      endpointTypes: [apigateway.EndpointType.REGIONAL],
    });

    this.apiId = this.api.restApiId;

    // Add v1 FHIR R4 path resource structure
    const v1 = this.api.root.addResource('v1');
    const fhir = v1.addResource('fhir');
    const r4   = fhir.addResource('r4');

    // Metadata endpoint — served from S3 (added fully in Task 9.5)
    r4.addResource('metadata');

    // ── CloudFormation Outputs ────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiEndpoint', {
      value:      this.api.url,
      exportName: `HB-ApiEndpoint-${envName}`,
    });
    new cdk.CfnOutput(this, 'UserPoolArn', {
      value:      this.userPool.userPoolArn,
      exportName: `HB-UserPoolArn-${envName}`,
    });
    new cdk.CfnOutput(this, 'UserPoolId', {
      value:      this.userPool.userPoolId,
      exportName: `HB-UserPoolId-${envName}`,
    });
  }
}
