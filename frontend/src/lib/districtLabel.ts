/** A district is its state plus its name (names repeat across states), so an
 * admin list that names districts says which state when it is not New Jersey,
 * where every district tracked so far is. Matches the backend's job names
 * (scheduler/job_names.py:district_label). */
export function districtLabel(d: { name: string; state?: string | null }): string {
  return !d.state || d.state === "NJ" ? d.name : `${d.name} (${d.state})`;
}
