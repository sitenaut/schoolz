import { Link } from "react-router-dom";
import { IconMail, IconSchool, IconShield, IconUsers } from "../../components/icons";
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
          <Link className="link-card" to="/gmail">
            <span className="ico">
              <IconMail />
            </span>
            <span>
              <b>Email scanner</b>
              <small>Connect Gmail to catch newsletter links</small>
            </span>
          </Link>
        </div>
      </SectionCard>
      <SectionCard title="Privacy" description="What schoolz stores and why." icon={<IconShield />}>
        <p className="note" style={{ margin: 0 }}>
          Everything is spelled out on the <Link to="/privacy">privacy &amp; cookies page</Link>. To delete your account, see{" "}
          <Link to="/account/security">Security</Link>.
        </p>
      </SectionCard>
    </>
  );
}
