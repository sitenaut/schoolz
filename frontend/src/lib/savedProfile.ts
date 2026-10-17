import { apiFetch } from "../api";
import type { FitAnswers } from "./localzFit";

/** "My services profile": the Localz answers saved to a signed-in person's
 * own account (backend/routers/saved_profile.py). Only they can read it;
 * saving needs consent first, and deleting is immediate. */

export type SavedProfileState = {
  /** False when the server can't encrypt, so nothing can be saved. */
  available: boolean;
  policy_version: number;
  consent: { policy_version: number; granted_at: string; current: boolean } | null;
  /** A profile exists, even if its answers wait for consent to be renewed. */
  saved: boolean;
  answers: FitAnswers | null;
  updated_at: string | null;
  last_used_at: string | null;
};

export class SavedProfileError extends Error {
  constructor(
    message: string,
    public code: string | null,
  ) {
    super(message);
  }
}

async function failed(res: Response): Promise<SavedProfileError> {
  try {
    const body = await res.json();
    return new SavedProfileError(typeof body.detail === "string" ? body.detail : "Something went wrong", body.code ?? null);
  } catch {
    return new SavedProfileError("Something went wrong", null);
  }
}

const URL = "/me/saved-answers";

export async function fetchSavedProfile(): Promise<SavedProfileState> {
  const res = await apiFetch(URL);
  if (!res.ok) throw await failed(res);
  return res.json();
}

export async function grantSavedProfileConsent(policyVersion: number): Promise<SavedProfileState> {
  const res = await apiFetch(`${URL}/consent`, {
    method: "POST",
    body: JSON.stringify({ purpose: "services_profile", policy_version: policyVersion }),
  });
  if (!res.ok) throw await failed(res);
  return res.json();
}

export async function saveSavedProfile(answers: FitAnswers): Promise<SavedProfileState> {
  const body = { ages: answers.ages, has: answers.has, focus: answers.focus, noStatusFirst: answers.noStatusFirst };
  const res = await apiFetch(URL, { method: "PUT", body: JSON.stringify(body) });
  if (!res.ok) throw await failed(res);
  return res.json();
}

/** Deletes the profile and withdraws consent, both at once. */
export async function deleteSavedProfile(): Promise<void> {
  const res = await apiFetch(URL, { method: "DELETE" });
  if (!res.ok) throw await failed(res);
}

export function consentIsCurrent(s: SavedProfileState | null): boolean {
  return !!s?.consent?.current;
}
