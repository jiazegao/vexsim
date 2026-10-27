// A recorded run as a video: the field canvas, captured while the run plays from its start to
// its end at the playhead's speed, saved as a WebM file.

import type { Playhead } from "./playhead";

const TYPES = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];

export function canRecordVideo(): boolean {
  return typeof MediaRecorder !== "undefined" && typeof HTMLCanvasElement.prototype.captureStream === "function";
}

/** Records `canvas` while `playhead` plays from its start; at the end, saves `name`.webm.
 * Pausing or seeking ends it without saving, as does `cancel()`. */
export class VideoExport {
  private recorder: MediaRecorder | null = null;
  private stopWatching: (() => void) | null = null;
  private saving = false;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly playhead: Playhead,
    private readonly name: string,
    private readonly onEnd: (saved: boolean, error?: string) => void,
  ) {}

  start(): void {
    const type = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    if (!type) {
      this.onEnd(false, "This browser can't record WebM video.");
      return;
    }
    const recorder = new MediaRecorder(this.canvas.captureStream(30), { mimeType: type, videoBitsPerSecond: 6_000_000 });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      for (const track of recorder.stream.getTracks()) track.stop();
      if (this.saving && chunks.length) download(new Blob(chunks, { type: "video/webm" }), `${this.name}.webm`);
      this.onEnd(this.saving && chunks.length > 0);
    };
    this.recorder = recorder;
    const playhead = this.playhead;
    playhead.pause();
    playhead.seek(playhead.start);
    recorder.start(250);
    playhead.play();
    let last = playhead.t;
    this.stopWatching = playhead.subscribe(() => {
      const atEnd = playhead.t >= playhead.end - 1e-6;
      const jumped = playhead.t < last - 1e-6; // sought back
      last = playhead.t;
      if (playhead.playing && !jumped) return;
      this.finish(atEnd && !jumped);
    });
  }

  cancel(): void {
    this.finish(false);
  }

  private finish(save: boolean): void {
    this.stopWatching?.();
    this.stopWatching = null;
    const recorder = this.recorder;
    this.recorder = null;
    if (!recorder || recorder.state === "inactive") return;
    this.saving = save;
    // the last frame, held a moment, so the video doesn't end the instant the robot stops
    setTimeout(() => recorder.stop(), save ? 400 : 0);
    if (!save) this.playhead.pause();
  }
}

export function download(blob: Blob, filename: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename.replace(/[^A-Za-z0-9._ -]+/g, "_");
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
}
