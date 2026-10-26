/** Bounded, cancellable downloads. No file bytes are stored in React state or caches. */
export const MEMORY_LIMIT = 32 * 1024 * 1024;
// Explicit native sharing needs a File; keep a separate, bounded allowance for videos.
export const SHARE_MEMORY_LIMIT = 64 * 1024 * 1024;
export const SHARE_TTL = 60_000;
export const SAVE_GRACE = 10_000;
export type DownloadState = {
  phase: 'connecting' | 'receiving' | 'ready' | 'sharing' | 'done' | 'cancelled' | 'error' | 'browser';
  received: number; total?: number; speed: number; started: number; lastData: number; message: string;
};
export function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}
let owner: symbol | undefined;
export function browserDownloadUrl(url: string, origin: string): string {
  const parsed = new URL(url, origin);
  if (parsed.origin === origin && /\/api\/media\//.test(parsed.pathname)) parsed.searchParams.set('download', 'true');
  return parsed.href;
}
export function formatBytes(value: number): string {
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
export class DownloadTask {
  private token = Symbol();
  private controller = new AbortController();
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private chunks: Uint8Array<ArrayBuffer>[] = [];
  private file?: File;
  private objectUrl?: string;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private state: DownloadState = { phase: 'connecting', received: 0, speed: 0, started: Date.now(), lastData: Date.now(), message: '正在连接…' };
  private notify: (state: DownloadState) => void;
  constructor(notify: (state: DownloadState) => void) { this.notify = notify; }
  private update(changes: Partial<DownloadState>) {
    this.state = { ...this.state, ...changes };
    if (!this.disposed) this.notify(this.state);
  }
  private release() {
    this.file = undefined;
    this.chunks.length = 0;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = undefined;
    clearTimeout(this.timer);
    this.timer = undefined;
    if (owner === this.token) owner = undefined;
  }
  dispose() {
    this.disposed = true;
    this.controller.abort();
    void this.reader?.cancel().catch(() => {});
    this.reader = undefined;
    this.release();
  }
  cancel() {
    this.update({ phase: 'cancelled', message: '已取消下载，临时数据已清理。' });
    this.dispose();
  }
  async start(url: string, name: string, share: boolean) {
    const limit = share ? SHARE_MEMORY_LIMIT : MEMORY_LIMIT;
    if (owner) {
      this.update({ phase: 'error', message: '另一个文件正在下载、等待保存或释放临时数据，请稍后重试或先取消它。' });
      return;
    }
    owner = this.token;
    this.update({});
    let keep = false;
    try {
      const response = await fetch(url, { signal: this.controller.signal, cache: 'no-store' });
      if (this.disposed) { void response.body?.cancel(); return; }
      if (!response.ok) throw new Error(response.status === 404 ? '文件已不存在。' : `下载失败（${response.status}），请重试。`);
      const length = Number(response.headers.get('content-length'));
      const encoding = response.headers.get('content-encoding');
      const total = !encoding || encoding === 'identity' ? (length > 0 && Number.isFinite(length) ? length : undefined) : undefined;
      if ((total && total > limit) || !response.body) {
        this.update({ phase: 'browser', message: '为节省手机内存，请使用浏览器下载，并在浏览器下载列表查看进度。' });
        return;
      }
      this.reader = response.body.getReader();
      this.update({ phase: 'receiving', total, message: '正在下载…' });
      let lastNotify = 0;
      while (true) {
        const { done, value } = await this.reader.read();
        if (this.disposed) return;
        if (done) break;
        const received = this.state.received + value.byteLength;
        if (received > limit) {
          this.update({ phase: 'browser', message: '文件超过网页下载上限，临时数据已清理。请使用浏览器重新下载。' });
          return;
        }
        this.chunks.push(value as Uint8Array<ArrayBuffer>);
        const now = Date.now();
        this.state = { ...this.state, received, total: this.state.total && received <= this.state.total ? this.state.total : undefined,
          lastData: now, speed: received / Math.max((now - this.state.started) / 1000, .1) };
        if (now - lastNotify > 150) { this.update({}); lastNotify = now; }
      }
      const type = response.headers.get('content-type')?.split(';')[0] || 'application/octet-stream';
      const extensions: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/avif': 'avif' };
      let filename = Array.from(name).map(c => c === '/' || c === '\\' || c.charCodeAt(0) < 32 ? '_' : c).join('') || 'download';
      if (extensions[type] && !/\.(png|jpe?g|webp|gif|svg|avif|bmp|ico)$/i.test(filename)) filename += '.' + extensions[type];
      this.file = new File(this.chunks, filename, { type });
      this.chunks.length = 0;
      if (share) {
        if (!navigator.canShare?.({ files: [this.file] })) throw new Error('当前浏览器不支持分享此文件，请使用下载。');
        this.update({ phase: 'ready', message: '已接收文件，请点“分享/保存”。临时文件将在 60 秒后自动清理。' });
        this.timer = setTimeout(() => { this.release(); this.update({ phase: 'done', message: '临时文件已清理，需要保存时请重新下载。' }); }, SHARE_TTL);
      } else {
        this.objectUrl = URL.createObjectURL(this.file);
        const link = document.createElement('a');
        link.href = this.objectUrl;
        link.download = this.file.name;
        link.target = '_blank';
        link.rel = 'noopener';
        document.body.append(link);
        link.click();
        link.remove();
        this.file = undefined;
        this.update({ phase: 'done', message: '文件已接收，已请求浏览器保存；请查看浏览器下载列表。' });
        // Allow the browser to consume the URL before revoking it. Never retain a File in state.
        this.timer = setTimeout(() => { this.release(); }, SAVE_GRACE);
      }
      keep = true;
    } catch (error) {
      if (!this.disposed) this.update({ phase: 'error', message: error instanceof Error && error.message
        ? (error instanceof TypeError ? '网络中断或外部文件限制下载，请重试或使用浏览器下载。' : error.message)
        : '下载失败，请重试或使用浏览器下载。' });
    } finally {
      this.controller.abort();
      void this.reader?.cancel().catch(() => {});
      this.reader = undefined;
      this.chunks.length = 0;
      if (!keep) this.release();
    }
  }
  async share() {
    if (!this.file || this.disposed || this.state.phase !== 'ready') return;
    clearTimeout(this.timer);
    try {
      // Called directly by a fresh click: Safari requires user activation.
      const pending = navigator.share({ files: [this.file] });
      this.update({ phase: 'sharing', message: '请在系统菜单中保存或分享。' });
      await pending;
      this.update({ phase: 'done', message: '分享操作已结束，临时文件已清理。' });
    } catch (error) {
      this.update({ phase: error instanceof Error && error.name === 'AbortError' ? 'cancelled' : 'error',
        message: '分享未完成，临时文件已清理；可重新下载。' });
    } finally { this.release(); }
  }
}
