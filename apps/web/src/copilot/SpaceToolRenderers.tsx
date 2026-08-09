import { Check, CircleAlert, LoaderCircle, Layers3 } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { useRenderTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { notifySpacesChanged } from "@/spaces/events";
import {
  cardContentSchema,
  cardDraftSchema,
  cardSizeSchema,
  cardTypeSchema,
  spaceToolResultSchema,
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
});
const renameCardParameters = spaceIdParameters.extend({ card_id: z.string(), title: z.string() });
const resizeCardParameters = spaceIdParameters.extend({ card_id: z.string(), size: cardSizeSchema });
const removeCardParameters = spaceIdParameters.extend({ card_id: z.string() });
const reorderCardsParameters = spaceIdParameters.extend({ card_ids: z.array(z.string()) });

export function SpaceToolRenderers() {
  useRenderTool({
    name: "render_ui",
    parameters: z.object({ card: cardDraftSchema }),
    render: ({ parameters, result, status }) => {
      const resultCard = status === "complete" ? parseToolResult(result)?.card : undefined;
      const parameterCard = cardDraftSchema.safeParse(parameters.card);
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
  });

  useSpaceToolRenderer("create_space", createSpaceParameters, "Creating Space", true);
  useSpaceToolRenderer("add_card_to_space", addCardParameters, "Adding card to Space", true);
  useSpaceToolRenderer("update_card_in_space", updateCardParameters, "Updating Space card", true);
  useSpaceToolRenderer("rename_card", renameCardParameters, "Renaming Space card", true);
  useSpaceToolRenderer("resize_card", resizeCardParameters, "Resizing Space card", true);
  useSpaceToolRenderer("remove_card_from_space", removeCardParameters, "Removing Space card", true);
  useSpaceToolRenderer("reorder_cards_in_space", reorderCardsParameters, "Reordering Space cards", true);
  useSpaceToolRenderer("list_spaces", z.object({}), "Reading Spaces", false);
  useSpaceToolRenderer("get_space", spaceIdParameters, "Reading Space", false);
  return null;
}

function useSpaceToolRenderer(
  name: string,
  parameters: z.ZodType,
  label: string,
  invalidatesSpaces: boolean,
) {
  useRenderTool(
    {
      name,
      parameters,
      render: ({ result, status }) => (
        <SpaceToolActivity
          invalidatesSpaces={invalidatesSpaces}
          label={label}
          result={status === "complete" ? result : undefined}
          status={status}
        />
      ),
    },
    [invalidatesSpaces, label, name, parameters],
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
  const parsed = result ? parseToolResult(result) : undefined;

  useEffect(() => {
    if (status === "complete" && invalidatesSpaces && parsed?.ok) notifySpacesChanged();
  }, [invalidatesSpaces, parsed?.ok, result, status]);

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
    <div className={`my-2 flex max-w-xl items-center gap-3 rounded-xl border px-4 py-3 text-sm ${failed ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-white text-slate-700"}`}>
      <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${failed ? "bg-red-100" : complete ? "bg-emerald-50 text-emerald-700" : "bg-blue-50 text-blue-700"}`}>
        {failed ? <CircleAlert aria-hidden="true" className="size-4" /> : complete ? <Check aria-hidden="true" className="size-4" /> : <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{label}</p>
        {detail ? <p className="mt-0.5 truncate text-xs opacity-70">{detail}</p> : null}
      </div>
      {!failed && complete ? <Layers3 aria-hidden="true" className="size-4 shrink-0 text-slate-400" /> : null}
    </div>
  );
}

function parseToolResult(result: string): SpaceToolResult | undefined {
  try {
    const parsedJson = JSON.parse(result) as unknown;
    const parsed = spaceToolResultSchema.safeParse(parsedJson);
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}
