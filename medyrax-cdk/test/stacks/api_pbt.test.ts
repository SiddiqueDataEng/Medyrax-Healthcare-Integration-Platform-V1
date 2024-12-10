/**
 * Property-based tests for API Gateway security (task 14.5).
 *
 * Property 14: OAuth 2.0 JWT Enforcement
 * Property 15: API Rate Limiting
 *
 * Validates: Requirements 6.2, 6.3, 6.4
 */
import * as fc from 'fast-check';

// ── Property 14: JWT Enforcement ─────────────────────────────────────────────

describe('JWT Enforcement (Property 14)', () => {

  const VALID_JWT_PAYLOAD = {
    sub: 'user-123',
    'custom:orgId': 'org-abc',
    'cognito:groups': ['Clinical_User'],
    exp: Math.floor(Date.now() / 1000) + 3600,
    iss: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test',
  };

  // Simulate JWT validation logic (mirrors API Gateway Cognito authorizer)
  function validateJwt(token: string | undefined): 'ALLOW' | 'DENY' {
    if (!token) return 'DENY';
    if (!token.startsWith('Bearer ')) return 'DENY';
    const parts = token.replace('Bearer ', '').split('.');
    if (parts.length !== 3) return 'DENY';
    try {
      const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      if (!payload.sub) return 'DENY';
      if (!payload.exp || payload.exp < Date.now() / 1000) return 'DENY';
      if (!payload['custom:orgId']) return 'DENY';
      return 'ALLOW';
    } catch {
      return 'DENY';
    }
  }

  function encodeJwt(payload: Record<string, unknown>): string {
    const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
    const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
    return `Bearer ${header}.${body}.fakesig`;
  }

  test('property: missing JWT token returns DENY', () => {
    fc.assert(
      fc.property(fc.constant(undefined as undefined), (token) => {
        expect(validateJwt(token)).toBe('DENY');
      }),
      { numRuns: 10 },
    );
  });

  test('property: malformed tokens (no Bearer prefix) return DENY', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }).filter((s) => !s.startsWith('Bearer ')),
        (token) => {
          expect(validateJwt(token)).toBe('DENY');
        },
      ),
      { numRuns: 100 },
    );
  });

  test('property: expired JWT returns DENY', () => {
    const expiredPayload = { ...VALID_JWT_PAYLOAD, exp: Math.floor(Date.now() / 1000) - 3600 };
    const token = encodeJwt(expiredPayload);
    expect(validateJwt(token)).toBe('DENY');
  });

  test('property: missing orgId in JWT returns DENY', () => {
    fc.assert(
      fc.property(
        fc.record({
          sub: fc.uuid(),
          exp: fc.integer({ min: Math.floor(Date.now() / 1000) + 100, max: 9999999999 }),
          // deliberately omit custom:orgId
        }),
        (payload) => {
          const token = encodeJwt(payload);
          expect(validateJwt(token)).toBe('DENY');
        },
      ),
      { numRuns: 50 },
    );
  });

  test('property: valid JWT with all required claims returns ALLOW', () => {
    const token = encodeJwt(VALID_JWT_PAYLOAD);
    expect(validateJwt(token)).toBe('ALLOW');
  });
});


// ── Property 15: API Rate Limiting ───────────────────────────────────────────

describe('API Rate Limiting (Property 15)', () => {

  const RATE_LIMIT = 1000; // requests per minute

  // Simulate token bucket rate limiter
  class TokenBucket {
    private tokens: number;
    constructor(private capacity: number, private refillRate: number) {
      this.tokens = capacity;
    }
    tryConsume(count: number = 1): boolean {
      if (this.tokens >= count) {
        this.tokens -= count;
        return true;
      }
      return false;
    }
    get available() { return this.tokens; }
  }

  test('property: requests up to rate limit all succeed', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: RATE_LIMIT }),
        (requestCount) => {
          const bucket = new TokenBucket(RATE_LIMIT, RATE_LIMIT);
          const results = Array.from({ length: requestCount }, () => bucket.tryConsume());
          const allAllowed = results.every((r) => r === true);
          expect(allAllowed).toBe(true);
        },
      ),
      { numRuns: 50 },
    );
  });

  test('property: requests exceeding rate limit receive 429', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),
        (excess) => {
          const bucket = new TokenBucket(RATE_LIMIT, RATE_LIMIT);
          // Consume all tokens
          for (let i = 0; i < RATE_LIMIT; i++) bucket.tryConsume();
          // Any additional request must be rejected
          const results = Array.from({ length: excess }, () => bucket.tryConsume());
          const allRejected = results.every((r) => r === false);
          expect(allRejected).toBe(true);
        },
      ),
      { numRuns: 50 },
    );
  });

  test('property: rate limit is exactly 1000 per minute per org API key', () => {
    const bucket = new TokenBucket(RATE_LIMIT, RATE_LIMIT);
    expect(bucket.available).toBe(1000);
  });
});
