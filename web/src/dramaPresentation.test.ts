import { describe, expect, it } from "vitest";
import { reviewIsCurrent } from "./dramaPresentation";
import type { Review, Shot } from "./dramaTypes";

const shot: Shot = {
  id: "s",
  episode_id: "e",
  version: 1,
  order: 0,
  visual: "近景",
  dialogue: "你好",
  speaker_id: "c",
  asset_ids: ["c"],
  duration: 3,
  framing: "closeup",
  sample: true,
  review_id: "r",
  outputs: { qc: { mechanical_passed: true, job_id: "new-generation" } },
};
const review: Review = {
  id: "r",
  qc_job_id: "new-generation",
  identity: true,
  continuity: true,
  voice: true,
  dialogue: true,
  lip_sync: true,
};
describe("production review validity", () => {
  it("accepts a complete review of the current generated clip", () =>
    expect(reviewIsCurrent(shot, review)).toBe(true));
  it("rejects a review of an older generation even if all checks passed", () =>
    expect(
      reviewIsCurrent(shot, { ...review, qc_job_id: "old-generation" }),
    ).toBe(false));
  it("does not present incomplete or missing reviews as accepted", () => {
    expect(reviewIsCurrent(shot, { ...review, lip_sync: false })).toBe(false);
    expect(reviewIsCurrent(shot)).toBe(false);
  });
});
