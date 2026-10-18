import type { InputHTMLAttributes } from "react";
import { nextPhoneValue } from "../../lib/phone";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: string;
  onChange: (value: string) => void;
};

/** A phone box that writes "(856) 555-0101" as you type, and an
 * extension after a comma: "(856) 555-0101, 12". A saved number in another
 * style shows as it was until it's edited. */
export function PhoneInput({ value, onChange, ...rest }: Props) {
  return (
    <input
      type="tel"
      inputMode="tel"
      autoComplete="tel"
      placeholder="(856) 555-0101"
      maxLength={40}
      {...rest}
      value={value}
      onChange={(e) => onChange(nextPhoneValue(value, e.target.value))}
    />
  );
}
