import { Check, CircleAlert, Layers3, LoaderCircle } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { validateTransform } from "@/lib/cardTransform/validateTransform";
import { browserEnv } from "@/lib/env";
import {
  addCardToSpace,
  createSpace,
  getSpace,
  listSpaces,
  removeCardFromSpace,
  renameCard,
  reorderCardsInSpace,
  resizeCard,
  updateCardInSpace,
} from "@/spaces/api";
import { notifySpacesChanged } from "@/spaces/events";
import {
  cardBindingSchema,
  cardContentSchema,
  cardDraftSchema,
  cardSizeSchema,
  cardTypeSchema,
  spaceToolResultSchema,
  type Space,
  type SpaceToolResult,
} from "@/spaces/types";

const SpaceCardView = lazy(() =>
  import("@/spaces/SpaceCardView").then((module) => ({ default: module.SpaceCardView })),
);

const createSpaceParameters = z.object({ name: z.string(), description: z.string().nullish() });
const spaceIdParameters = z.object({ space_id: z.string() });
const addCardParameters = spaceIdParameters.extend({ card: cardDraftSchema });
const updateCardParameters = spaceIdParameters.extend({
  card_id: z.string(),
  content: cardContentSchema,
  card_type: cardTypeSchema.nullish(),
  subtitle: z.string().nullish(),
  binding: cardBindingSchema.nullish(),
});
const renameCardParameters = spaceIdParameters.extend({ card_id: z.string(), title: z.string() });
const resizeCardParameters = spaceIdParameters.extend({ card_id: z.string(), size: cardSizeSchema });
const removeCardParameters = spaceIdParameters.extend({ card_id: z.string() });
const reorderCardsParameters = spaceIdParameters.extend({ card_ids: z.array(z.string()) });
const validateTransformParameters = z.object({
  code: z.string(),
  raw: z.unknown(),
  card_type: cardTypeSchema.nullish(),
});

const liveCardGuidance =
  "For a live card, call its read-only source tool once, write a pure binding.transform function transform(raw), validate it with validate_card_transform, then persist it.";

export function SpaceFrontendTools() {
  useFrontendTool(
    {
      name: "validate_card_transform",
      description: "Validate a live card transform against a raw source sample before persisting it.",
      parameters: validateTransformParameters,
      handler: async ({ code, raw, card_type }) => validateTransform({ code, raw, cardType: card_type ?? undefined }),
      render: ({ result, status }) => (
        <ToolActivity
          detail={validationDetail(result, status)}
          failed={status === "complete" && !isValidationOk(result)}
          label="Validating transform"
          status={status}
        />
      ),
    },
    [],
  );

  useFrontendTool(
    {
      name: "render_ui",
      description: "Render a transient KPI, table, chart, details, object list, or markdown card in this conversation.",
      parameters: z.object({ card: cardDraftSchema }),
      handler: async ({ card }) => {
        const now = new Date().toISOString();
        return {
          ok: true,
          transient: true,
          card: {
            ...cardDraftSchema.parse(card),
            id: crypto.randomUUID(),
            created_at: now,
            updated_at: now,
            refresh_status: "fresh",
          },
        } satisfies SpaceToolResult;
      },
      render: ({ args, result, status }) => {
        const resultCard = status === "complete" ? parseToolResult(result)?.card : undefined;
        const parameterCard = cardDraftSchema.safeParse(args.card);
        const card = resultCard ?? (parameterCard.success ? parameterCard.data : undefined);
        if (!card) return <ToolActivity label="Preparing visualization" status={status} />;
        return (
          <div className="my-3 max-w-3xl">
            <Suspense fallback={<div className="h-56 animate-pulse rounded-xl border border-slate-200 bg-slate-50" />}>
              <SpaceCardView card={card} compact />
            </Suspense>
          </div>
        );
      },
    },
    [],
  );

  useFrontendTool(
    {
      name: "create_space",
      description: "Create a persistent visual workspace for reusable cards.",
      parameters: createSpaceParameters,
      handler: ({ name, description }) => mutate(() => createSpace(browserEnv, name, description)),
      render: renderActivity("Creating Space", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "add_card_to_space",
      description: `Add a visualization card to an existing Space. ${liveCardGuidance}`,
      parameters: addCardParameters,
      handler: ({ space_id, card }) => mutate(() => addCardToSpace(browserEnv, space_id, card)),
      render: renderActivity("Adding card to Space", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "update_card_in_space",
      description: `Update a Space card's content, type, subtitle, or binding. ${liveCardGuidance}`,
      parameters: updateCardParameters,
      handler: ({ space_id, card_id, ...update }) =>
        mutate(() => updateCardInSpace(browserEnv, space_id, card_id, update)),
      render: renderActivity("Updating Space card", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "rename_card",
      description: "Rename one card in a Space.",
      parameters: renameCardParameters,
      handler: ({ space_id, card_id, title }) => mutate(() => renameCard(browserEnv, space_id, card_id, title)),
      render: renderActivity("Renaming Space card", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "resize_card",
      description: "Change a Space card's responsive display size.",
      parameters: resizeCardParameters,
      handler: ({ space_id, card_id, size }) => mutate(() => resizeCard(browserEnv, space_id, card_id, size)),
      render: renderActivity("Resizing Space card", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "remove_card_from_space",
      description: "Remove one card from a Space.",
      parameters: removeCardParameters,
      handler: ({ space_id, card_id }) => mutate(() => removeCardFromSpace(browserEnv, space_id, card_id)),
      render: renderActivity("Removing Space card", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "reorder_cards_in_space",
      description: "Set the display order using every current card id exactly once.",
      parameters: reorderCardsParameters,
      handler: ({ space_id, card_ids }) => mutate(() => reorderCardsInSpace(browserEnv, space_id, card_ids)),
      render: renderActivity("Reordering Space cards", true),
    },
    [],
  );

  useFrontendTool(
    {
      name: "list_spaces",
      description: "List persistent Spaces before selecting one to read or change.",
      parameters: z.object({}),
      handler: () => runTool(async () => ({ ok: true, spaces: await listSpaces(browserEnv) })),
      render: renderActivity("Reading Spaces", false),
    },
    [],
  );

  useFrontendTool(
    {
      name: "get_space",
      description: "Read a Space and all of its current cards.",
      parameters: spaceIdParameters,
      handler: ({ space_id }) => runTool(async () => ({ ok: true, space: await getSpace(browserEnv, space_id) })),
      render: renderActivity("Reading Space", false),
    },
    [],
  );

  return null;
}

function renderActivity(label: string, invalidatesSpaces: boolean) {
  return ({ result, status }: { result: string | undefined; status: "inProgress" | "executing" | "complete" }) => (
    <SpaceToolActivity invalidatesSpaces={invalidatesSpaces} label={label} result={result} status={status} />
  );
}

function SpaceToolActivity({
  invalidatesSpaces,
  label,
  result,
  status,
}: {
  invalidatesSpaces: boolean;
  label: string;
  result: string | undefined;
  status: "inProgress" | "executing" | "complete";
}) {
  const parsed = status === "complete" ? parseToolResult(result) : undefined;

  useEffect(() => {
    if (status === "complete" && invalidatesSpaces && parsed?.ok) notifySpacesChanged();
  }, [invalidatesSpaces, parsed?.ok, status]);

  const failed = status === "complete" && parsed?.ok === false;
  const detail = failed
    ? parsed.error?.message
    : parsed?.space
      ? `${parsed.space.name} · ${parsed.space.cards.length} cards`
      : parsed?.spaces
        ? `${parsed.spaces.length} Spaces`
        : undefined;

  return <ToolActivity detail={detail} failed={failed} label={label} status={status} />;
}

function ToolActivity({
  detail,
  failed = false,
  label,
  status,
}: {
  detail?: string;
  failed?: boolean;
  label: string;
  status: "inProgress" | "executing" | "complete";
}) {
  const complete = status === "complete";
  return (
    <div
      className={`my-2 flex max-w-xl items-center gap-3 rounded-xl border px-4 py-3 text-sm ${failed ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-white text-slate-700"}`}
    >
      <span
        className={`grid size-8 shrink-0 place-items-center rounded-lg ${failed ? "bg-red-100" : complete ? "bg-emerald-50 text-emerald-700" : "bg-blue-50 text-blue-700"}`}
      >
        {failed ? (
          <CircleAlert aria-hidden="true" className="size-4" />
        ) : complete ? (
          <Check aria-hidden="true" className="size-4" />
        ) : (
          <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{label}</p>
        {detail ? <p className="mt-0.5 truncate text-xs opacity-70">{detail}</p> : null}
      </div>
      {!failed && complete ? <Layers3 aria-hidden="true" className="size-4 shrink-0 text-slate-400" /> : null}
    </div>
  );
}

async function mutate(operation: () => Promise<Space>): Promise<SpaceToolResult> {
  return runTool(async () => ({ ok: true, space: await operation() }));
}

async function runTool(operation: () => Promise<SpaceToolResult>): Promise<SpaceToolResult> {
  try {
    return await operation();
  } catch (error) {
    return {
      ok: false,
      error: { code: "space_request_failed", message: error instanceof Error ? error.message : "Space request failed" },
    };
  }
}

function parseToolResult(result: string | undefined): SpaceToolResult | undefined {
  if (!result) return undefined;
  try {
    const parsed = spaceToolResultSchema.safeParse(JSON.parse(result) as unknown);
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}

function normalizeValidation(result: unknown): { ok: boolean; message?: string } | undefined {
  let value = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value) as unknown;
    } catch {
      return undefined;
    }
  }
  if (value && typeof value === "object" && "ok" in value) {
    const record = value as { ok?: unknown; message?: unknown };
    return { ok: record.ok === true, message: typeof record.message === "string" ? record.message : undefined };
  }
  return undefined;
}

function isValidationOk(result: unknown): boolean {
  return normalizeValidation(result)?.ok ?? true;
}

function validationDetail(result: unknown, status: "inProgress" | "executing" | "complete"): string | undefined {
  if (status !== "complete") return undefined;
  const parsed = normalizeValidation(result);
  return parsed?.ok ? "Transform is valid" : parsed?.message;
}
