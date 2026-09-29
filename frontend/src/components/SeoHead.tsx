import { Helmet } from "react-helmet-async";
import { CURRENT_LANG, DEFAULT_LANG, LANGUAGES, isTranslatedPath, localizedPath } from "../lib/i18n";
import { SITE_URL } from "../lib/site";

type Props = {
  title: string;
  description: string;
  /** Path only (e.g. "/schools/bret-harte-elementary") - resolved against
   * the current origin so this works unchanged in local/prod/preview. */
  path: string;
  image?: string;
  /** Arbitrary JSON-LD object(s) (schema.org) describing the page's
   * content - e.g. an EducationalOrganization for a school page. */
  jsonLd?: object | object[];
};

/** Per-route <title>/meta/canonical/Open Graph tags, since index.html only
 * has one static title otherwise. This alone doesn't make content visible
 * to a non-JS crawler (see the prerender proxy in
 * frontend/nginx.conf.template for that) - it's what makes a shared link
 * preview correctly and gives Googlebot's own render pass real per-page
 * titles/descriptions instead of one generic one for every route. */
export function SeoHead({ title, description, path, image, jsonLd }: Props) {
  // `path` is router-relative, so each language gets its own canonical and
  // the set is cross-linked with hreflang - without it Google treats /es/...
  // as a duplicate of the English page instead of its translation.
  const translated = isTranslatedPath(path);
  const pageLang = translated ? CURRENT_LANG : DEFAULT_LANG;
  const url = `${SITE_URL}${localizedPath(path, pageLang)}`;
  const jsonLdList = jsonLd ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]) : [];
  return (
    <Helmet>
      <title>{title}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={url} />
      {translated &&
        LANGUAGES.map((l) => <link key={l.code} rel="alternate" hrefLang={l.code} href={`${SITE_URL}${localizedPath(path, l.code)}`} />)}
      {translated && <link rel="alternate" hrefLang="x-default" href={`${SITE_URL}${localizedPath(path, DEFAULT_LANG)}`} />}
      <meta property="og:locale" content={CURRENT_LANG === "es" ? "es_US" : "en_US"} />
      <meta property="og:type" content="website" />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={url} />
      {image && <meta property="og:image" content={image} />}
      <meta name="twitter:card" content={image ? "summary_large_image" : "summary"} />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      {jsonLdList.map((obj, i) => (
        <script key={i} type="application/ld+json">
          {JSON.stringify(obj)}
        </script>
      ))}
    </Helmet>
  );
}
