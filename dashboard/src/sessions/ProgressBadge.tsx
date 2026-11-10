import type { Session } from "./api";

type Props = Pick<Session, "status" | "progress" | "stage" | "error">;

const TONE = {
  uploading: "neutral",
  queued: "warning",
  processing: "warning",
  ready: "success",
  failed: "danger",
} as const;

const LABEL = {
  uploading: "Uploading",
  queued: "Queued",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
} as const;

export function ProgressBadge({ status, progress, stage, error }: Props) {
  let text: string = LABEL[status];
  if (status === "queued" || status === "processing") {
    text += ` ${progress}%`;
    if (stage) text += ` · ${stage}`;
  } else if (status === "failed" && error) {
    text += ` · ${error}`;
  }
  return <span className={`badge badge-${TONE[status]} num`}>{text}</span>;
}
