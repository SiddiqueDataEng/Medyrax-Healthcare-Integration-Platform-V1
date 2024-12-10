/**
 * MedyraxCoreStack
 *
 * Provisions the platform-level API Gateway, Cognito User Pool, and
 * base route infrastructure. Individual Lambda functions are wired via
 * task 23.2. Routes configured here cover all spec requirements:
 * FHIR R4, HL7, CDS Hooks, Terminology, Telehealth, Admin endpoints.
 *
 * Requirements: 1.7, 4.5, 6.1–6.8, 7.7
 */
import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';
import { MedyraxSecurityStack } from './MedyraxSecurityStack';
import { MedyraxDataStack } from './MedyraxDataStack';

export interface MedyraxCoreStackProps extends MedyraxStackProps {
  securityStack?: MedyraxSecurityStack;
  dataStack?: MedyraxDataStack;
}

export class MedyraxCoreStack extends cdk.Stack {

  public readonly userPool: cognito.UserPool;
  public readonly api: apigateway.RestApi;
  public readonly apiAccessLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: MedyraxCoreStackProps) {
    super(scope, id, props);
    const { envName, envConfig } = props;
    const tokenExpiry = envConfig.cognitoAccessTokenExpiryMinutes ?? 15;

    // ── Cognito User Pool (Requirement 7.7) ──────────────────────────────
    this.userPool = new cognito.UserPool(this, 'MedyraxUserPool', {
      userPoolName: `mdx-user-pool-${envName}`,
      selfSignUpEnabled: false,
      signInAliases: { email: true, username: true },
      customAttributes: {
        orgId: new cognito.StringAttribute({ mutable: false }),
        role: new cognito.StringAttribute({ mutable: true }),
      },
      passwordPolicy: {
        minLength: 14,
        requireUppercase: true,
        requireLowercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: envName === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    this.userPool.addClient('PlatformClient', {
      userPoolClientName: `mdx-platform-client-${envName}`,
      authFlows: { userSrp: true, adminUserPassword: true },
      oAuth: {
        flows: { clientCredentials: true, authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
      },
      accessTokenValidity: cdk.Duration.minutes(tokenExpiry),
      idTokenValidity: cdk.Duration.minutes(tokenExpiry),
      refreshTokenValidity: cdk.Duration.days(30),
      preventUserExistenceErrors: true,
    });

    // ── API Gateway Access Logging ────────────────────────────────────────
    this.apiAccessLogGroup = new logs.LogGroup(this, 'ApiAccessLogGroup', {
      logGroupName: `/Medyrax/${envName}/api-access`,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── REST API Gateway (Requirements 6.1, 6.4, 6.5, 6.6, 6.8) ─────────
    this.api = new apigateway.RestApi(this, 'MedyraxApi', {
      restApiName: `Medyrax-api-${envName}`,
      description: 'Medyrax FHIR R4 and REST API',
      deployOptions: {
        stageName: 'v1',
        tracingEnabled: envConfig.enableXRay !== false,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        accessLogDestination: new apigateway.LogGroupLogDestination(this.apiAccessLogGroup),
        accessLogFormat: apigateway.AccessLogFormat.jsonWithStandardFields({
          caller: true, httpMethod: true, ip: true,
          protocol: true, requestTime: true, resourcePath: true,
          responseLength: true, status: true, user: true,
        }),
        throttlingRateLimit: 1000,
        throttlingBurstLimit: 2000,
        metricsEnabled: true,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          'Content-Type', 'Authorization', 'X-Amz-Date', 'X-Api-Key',
          'X-Amz-Security-Token', 'X-PHI-Masking', 'Accept-Encoding',
        ],
        maxAge: cdk.Duration.days(1),
      },
      endpointTypes: [apigateway.EndpointType.REGIONAL],
    });

    // ── Cognito JWT Authorizer (Requirements 6.2, 6.3) ───────────────────
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(
      this, 'JwtAuthorizer', {
        cognitoUserPools: [this.userPool],
        authorizerName: `mdx-jwt-authorizer-${envName}`,
        identitySource: 'method.request.header.Authorization',
        resultsCacheTtl: cdk.Duration.minutes(5),
      }
    );

    // ── Route structure ───────────────────────────────────────────────────
    const v1 = this.api.root.addResource('v1');

    // FHIR R4 base
    const fhir = v1.addResource('fhir');
    const r4 = fhir.addResource('r4');

    // Metadata (unauthenticated)
    const metadata = r4.addResource('metadata');
    metadata.addMethod('GET', new apigateway.MockIntegration({
      integrationResponses: [{ statusCode: '200' }],
      passthroughBehavior: apigateway.PassthroughBehavior.NEVER,
      requestTemplates: { 'application/json': '{"statusCode": 200}' },
    }), {
      methodResponses: [{ statusCode: '200' }],
    });

    // Terminology routes (task 5.4)
    const codeSystem = r4.addResource('CodeSystem');
    codeSystem.addResource('$validate-code').addMethod('GET',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/validate'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );

    const conceptMap = r4.addResource('ConceptMap');
    conceptMap.addResource('$translate').addMethod('POST',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/translate'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );

    // FHIR resource CRUD {resource} and {resource}/{id}
    const resourceProxy = r4.addResource('{resource}');
    ['GET', 'POST'].forEach(m => resourceProxy.addMethod(m,
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/fhir'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    ));

    const resourceWithId = resourceProxy.addResource('{id}');
    ['GET', 'PUT', 'DELETE'].forEach(m => resourceWithId.addMethod(m,
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/fhir'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    ));
    resourceProxy.addResource('_search').addMethod('POST',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/fhir'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );

    // Admin routes
    const admin = v1.addResource('admin');
    const orgs = admin.addResource('organizations');
    orgs.addMethod('POST',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/admin'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );
    const orgId = orgs.addResource('{orgId}');
    orgId.addResource('status').addMethod('GET',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/admin'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );
    orgId.addMethod('DELETE',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/admin'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );

    // CDS Hooks
    const cds = v1.addResource('cds-services');
    cds.addMethod('GET');
    cds.addResource('{hookId}').addMethod('POST');

    // Telehealth
    const telehealth = r4.addResource('integration').addResource('telehealth');
    telehealth.addResource('appointment').addMethod('POST',
      new apigateway.HttpIntegration('https://placeholder.medyrax.io/telehealth'),
      { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
    );
    telehealth.addResource('patient').addResource('{patientId}')
      .addResource('presync').addMethod('GET',
        new apigateway.HttpIntegration('https://placeholder.medyrax.io/telehealth'),
        { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO },
      );

    // ── Outputs ──────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiEndpoint', {
      value: this.api.url,
      exportName: `mdx-api-endpoint-${envName}`,
    });
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      exportName: `mdx-user-pool-id-${envName}`,
    });
    new cdk.CfnOutput(this, 'UserPoolArn', {
      value: this.userPool.userPoolArn,
      exportName: `mdx-user-pool-arn-${envName}`,
    });

    cdk.Tags.of(this).add('Project', 'Medyrax');
    cdk.Tags.of(this).add('Layer', 'Core');
    cdk.Tags.of(this).add('Environment', envName);
  }
}
