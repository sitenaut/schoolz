/** Display label for School.school_type. "other" is a real backend value
 * (services/preschool_locations.py writes every private preschool/
 * daycare provider as school_type="other", matching Malberg's existing
 * precedent) - but showing the literal word "other" to a parent reads as
 * a bug, not a category. Every school currently tagged "other" is in
 * fact a preschool/early-childhood provider (the district's own
 * "Preschool Locations" list), so "Preschool" is accurate, not a euphemism. */
export function schoolTypeLabel(type: string | null): string | null {
  if (!type) return null;
  if (type === "other") return "Preschool";
  if (type === "elementary" || type === "middle" || type === "high") {
    return `${type[0].toUpperCase()}${type.slice(1)} school`;
  }
  return type[0].toUpperCase() + type.slice(1);
}
