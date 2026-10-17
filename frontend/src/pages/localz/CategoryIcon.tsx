import { IconBag, IconBasket, IconCoins, IconFamily, IconHeart, IconHouseKey, IconLanguage, IconShield } from "../../components/icons";

const ICONS: Record<string, (p: { className?: string }) => JSX.Element> = {
  food: IconBasket,
  english: IconLanguage,
  "housing-bills": IconHouseKey,
  health: IconHeart,
  "kids-family": IconFamily,
  "money-work": IconCoins,
  "legal-safety": IconShield,
  "everyday-needs": IconBag,
};

export function CategoryIcon({ category, className }: { category: string; className?: string }) {
  const Icon = ICONS[category] ?? IconBag;
  return <Icon className={className} />;
}
