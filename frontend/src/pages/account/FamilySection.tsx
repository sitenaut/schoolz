import { Link } from "react-router-dom";
import { IconSchool, IconUsers } from "../../components/icons";
import { SectionCard } from "../../components/ui/SectionCard";

export function FamilySection() {
  return (
    <>
      <SectionCard title="Your family" description="The personal layer - only you (and guardians you share a child with) see this." icon={<IconUsers />}>
        <div className="link-grid">
          <Link className="link-card" to="/children">
            <span className="ico">
              <IconUsers />
            </span>
            <span>
              <b>My children</b>
              <small>Link a child, invite the other parent</small>
            </span>
          </Link>
          <Link className="link-card" to="/start">
            <span className="ico">
              <IconSchool />
            </span>
            <span>
              <b>Schools on my Today page</b>
              <small>Pick which schools you follow</small>
            </span>
          </Link>
        </div>
      </SectionCard>
    </>
  );
}
