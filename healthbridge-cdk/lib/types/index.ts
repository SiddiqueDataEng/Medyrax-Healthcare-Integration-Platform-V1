/**
 * @hb/types — Shared TypeScript types package for Medyrax™ CDK infrastructure.
 *
 * Contains:
 * - CDK construct prop interfaces
 * - Event envelope interfaces (TypeScript mirror of Java EventEnvelope)
 * - Environment configuration interfaces
 * - Common utility types
 *
 * Requirements 1.1, 2.1, 5.1, 13.1 — shared type definitions used across
 * all CDK stacks and TypeScript tooling.
 */

// ── Re-exports ────────────────────────────────────────────────────────────────
export * from './EnvironmentConfig';
export * from './EventEnvelope';
export * from './FhirResourceType';
export * from './ConstructProps';
