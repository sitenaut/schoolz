// One JSON file per area (locales/es/<area>.json), merged here, so several
// people can add strings without editing the same file. Keys are the English
// source text.
const files = import.meta.glob("./hi/*.json", { eager: true, import: "default" }) as Record<string, Record<string, string>>;

export default Object.assign({}, ...Object.values(files)) as Record<string, string>;
