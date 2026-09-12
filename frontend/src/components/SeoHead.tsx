import { Helmet } from "react-helmet-async";
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
  const url = `${SITE_URL}${path}`;
  const jsonLdList = jsonLd ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]) : [];
  return (
    <Helmet>
      <title>{title}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={url} />
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
