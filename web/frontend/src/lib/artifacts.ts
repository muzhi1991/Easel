export interface Artifact {
  url: string;
  name: string;
  kind: 'image' | 'html' | 'video' | 'audio' | 'pdf';
}

function hasUnsafeCharacters(value: string): boolean {
  return Array.from(value).some(character => character === '\\' || character.charCodeAt(0) < 32);
}

export function artifactFromUrl(url: string): Artifact | null {
  const prefix = url.startsWith('/api/media/') ? '/api/media/'
    : url.startsWith('#/outputs/') ? '#/outputs/' : null;
  if (!prefix || hasUnsafeCharacters(url)) return null;
  try {
    const encodedPath = url.slice(prefix.length).split(/[?#]/)[0];
    const path = decodeURIComponent(encodedPath);
    if (hasUnsafeCharacters(path)
        || path.split('/').some(part => !part || part === '.' || part === '..')) return null;
    const name = path.split('/').at(-1) || '';
    const extension = name.split('.').at(-1)?.toLowerCase();
    const kind = /^(png|jpe?g|gif|webp|svg|avif|bmp|ico)$/.test(extension || '') ? 'image'
      : /^(html|htm)$/.test(extension || '') ? 'html'
      : /^(mp4|webm|mov|m4v)$/.test(extension || '') ? 'video'
      : /^(mp3|wav|ogg|m4a|flac)$/.test(extension || '') ? 'audio'
      : extension === 'pdf' ? 'pdf' : null;
    const target = prefix === '#/outputs/'
      ? '/api/media/' + path.split('/').map(encodeURIComponent).join('/') : url;
    return kind ? { url: target, name, kind } : null;
  } catch {
    return null;
  }
}

/** Only call for actual img elements; arbitrary remote links are not media. */
export function artifactFromImageUrl(url: string): Artifact | null {
  const local = artifactFromUrl(url);
  if (local) return local.kind === 'image' ? local : null;
  if (hasUnsafeCharacters(url)) return null;
  try {
    const parsed = new URL(url.startsWith('//') ? `https:${url}` : url);
    if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    let name = parsed.pathname.split('/').at(-1) || 'image';
    try { name = decodeURIComponent(name); } catch { /* Keep encoded name. */ }
    return { url: parsed.href, name, kind: 'image' };
  } catch { return null; }
}

function artifactKey(url: string): string {
  // Remote query strings may identify entirely different generated images.
  if (!url.startsWith('/api/media/')) return url;
  return decodeURIComponent(url.split(/[?#]/)[0]);
}

export function extractArtifacts(html: string): { html: string; artifacts: Artifact[]; archives: string[] } {
  const document = new DOMParser().parseFromString(html, 'text/html');
  const artifacts: Artifact[] = [];
  const archives: string[] = [];
  const seen = new Set<string>();
  for (const element of document.querySelectorAll('img[src], a[href]')) {
    const url = element.getAttribute(element.tagName === 'IMG' ? 'src' : 'href') || '';
    const archive = archiveFromUrl(url);
    if (archive && !archives.includes(archive)) archives.push(archive);
    const artifact = element.tagName === 'IMG' ? artifactFromImageUrl(url) : artifactFromUrl(url);
    if (!artifact) continue;
    const key = artifactKey(artifact.url);
    if (!seen.has(key)) {
      seen.add(key);
      artifacts.push(artifact);
    }
    if (element.tagName === 'IMG') {
      const link = document.createElement('a');
      link.href = artifact.url;
      link.textContent = artifact.name;
      link.target = '_blank';
      link.rel = 'noreferrer';
      if (element.parentElement?.tagName === 'A') element.replaceWith(document.createTextNode(artifact.name));
      else element.replaceWith(link);
    }
  }
  return { html: document.body.innerHTML, artifacts, archives };
}

export function archiveFromUrl(url: string): string | null {
  const prefix = url.startsWith('/api/media/') ? '/api/media/'
    : url.startsWith('#/outputs/') ? '#/outputs/' : null;
  if (!prefix || hasUnsafeCharacters(url)) return null;
  try {
    const path = decodeURIComponent(url.slice(prefix.length).split(/[?#]/)[0]);
    if (hasUnsafeCharacters(path) || !/\.zip$/i.test(path)
        || path.split('/').some(part => !part || part === '.' || part === '..')) return null;
    return path;
  } catch {
    return null;
  }
}

export function mergeArtifacts(...groups: Artifact[][]): Artifact[] {
  const seen = new Set<string>();
  return groups.flat().filter(artifact => {
    const key = artifactKey(artifact.url);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function fitArtifact(width: number, height: number, availableWidth: number, availableHeight: number) {
  const scale = Math.min(1, Math.max(1, availableWidth) / Math.max(1, width),
    Math.max(1, availableHeight) / Math.max(1, height));
  return { scale, width: width * scale, height: height * scale };
}
