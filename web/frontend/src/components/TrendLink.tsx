/** Open news as a top-level page: publishers can block frames or need login cookies.
 * Keep the radar mounted in its original tab, including its channel and scroll state.
 */
export default function TrendLink({ url, title, className }: {
  url?: string; title: string; className: string;
}) {
  const safeUrl = url && /^https?:\/\//i.test(url) ? url : undefined;
  return <a className={className} href={safeUrl} target="_blank" rel="noopener noreferrer" title={title}>
    {title}
  </a>;
}
