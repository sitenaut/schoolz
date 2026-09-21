import { Link } from "react-router-dom";
import { IconLock } from "../../components/icons";
import { SectionCard } from "../../components/ui/SectionCard";

export function PrivacySection() {
  return (
    <SectionCard title="Privacy" description="What schoolz stores and why." icon={<IconLock />}>
      <p className="note" style={{ margin: 0 }}>
        Everything is spelled out on the <Link to="/privacy">privacy &amp; cookies page</Link>. To delete your account, see{" "}
        <Link to="/account/security">Security</Link>.
      </p>
    </SectionCard>
  );
}
