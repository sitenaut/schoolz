import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import type { SchoolToday } from "../types";

/** Goes up by one each time the signed-in person changes while a page stays
 * mounted: a sign-out from the user menu (which navigates to "/", no remount
 * when already there), a sign-in from the header's popover. Not when auth
 * first settles on load - requests made before that already carried the
 * stored session's token, and refetching then would double every load. */
export function useViewerEpoch(): number {
  const { user, loading } = useAuth();
  const viewer = loading ? undefined : (user?.id ?? null);
  const [seen, setSeen] = useState({ viewer, epoch: 0 });
  if (viewer !== undefined && viewer !== seen.viewer) {
    const epoch = seen.viewer === undefined ? seen.epoch : seen.epoch + 1;
    setSeen({ viewer, epoch });
    return epoch;
  }
  return seen.epoch;
}

/** A Today card without the signed-in viewer's own layer: their child's
 * class right now and today's special, which a shared device must not keep
 * showing after they sign out. */
export function withoutViewerLayer(today: SchoolToday): SchoolToday {
  return { ...today, my_specials: [], my_current_classes: [] };
}
