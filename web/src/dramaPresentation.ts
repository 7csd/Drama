import type { Review, Shot } from "./dramaTypes";

export function reviewIsCurrent(shot: Shot, review?: Review): boolean {
  return (
    !!review &&
    !!shot.outputs.qc?.mechanical_passed &&
    !!shot.outputs.qc.job_id &&
    review.qc_job_id === shot.outputs.qc.job_id &&
    review.id === shot.review_id &&
    ["identity", "continuity", "voice", "dialogue", "lip_sync"].every(
      (key) => review[key as keyof Review] === true,
    )
  );
}
