import { z } from "zod";

export const cardTypeSchema = z.enum([
  "kpi",
  "table",
  "line-chart",
  "bar-chart",
  "details",
  "object-list",
  "markdown",
]);
export const cardSizeSchema = z.enum(["small", "medium", "large", "full"]);

const kpiMetricSchema = z.object({
  label: z.string(),
  value: z.union([z.string(), z.number()]),
  unit: z.string().nullish(),
  trend: z.string().nullish(),
  trend_direction: z.enum(["up", "down", "neutral"]).nullish(),
});

const tableColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  align: z.enum(["left", "center", "right"]).default("left"),
});

const chartSeriesSchema = z.object({
  name: z.string(),
  values: z.array(z.number()),
  color: z.string().nullish(),
});

const detailFieldSchema = z.object({
  label: z.string(),
  value: z.union([z.string(), z.number(), z.boolean(), z.null()]),
  status: z.enum(["positive", "critical", "negative", "neutral"]).nullish(),
});

const objectListItemSchema = z.object({
  title: z.string(),
  subtitle: z.string().nullish(),
  value: z.union([z.string(), z.number(), z.null()]).optional(),
  status: z.enum(["positive", "critical", "negative", "neutral"]).nullish(),
});

export const cardContentSchema = z.object({
  metrics: z.array(kpiMetricSchema).default([]),
  columns: z.array(tableColumnSchema).default([]),
  rows: z.array(z.record(z.string(), z.unknown())).default([]),
  categories: z.array(z.string()).default([]),
  series: z.array(chartSeriesSchema).default([]),
  fields: z.array(detailFieldSchema).default([]),
  items: z.array(objectListItemSchema).default([]),
  markdown: z.string().nullish(),
});

export const cardDraftSchema = z.object({
  type: cardTypeSchema,
  title: z.string(),
  subtitle: z.string().nullish(),
  size: cardSizeSchema.default("medium"),
  content: cardContentSchema,
});

export const spaceCardSchema = cardDraftSchema.extend({
  id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const spaceSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  cards: z.array(spaceCardSchema),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const spaceSummarySchema = spaceSchema.omit({ cards: true }).extend({
  card_count: z.number().int(),
});

export const spaceToolResultSchema = z.object({
  ok: z.boolean(),
  transient: z.boolean().optional(),
  card: spaceCardSchema.optional(),
  space: spaceSchema.optional(),
  spaces: z.array(spaceSummarySchema).optional(),
  error: z.object({ code: z.string(), message: z.string() }).optional(),
});

export type CardDraft = z.infer<typeof cardDraftSchema>;
export type CardSize = z.infer<typeof cardSizeSchema>;
export type Space = z.infer<typeof spaceSchema>;
export type SpaceCard = z.infer<typeof spaceCardSchema>;
export type SpaceSummary = z.infer<typeof spaceSummarySchema>;
export type SpaceToolResult = z.infer<typeof spaceToolResultSchema>;
