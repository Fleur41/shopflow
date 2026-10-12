"use client";

import { CameraOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

// The Barcode Detection API (Chrome on Android, among others) isn't in TypeScript's DOM types yet.
type DetectedBarcode = { rawValue: string };
type BarcodeDetectorLike = { detect(source: HTMLVideoElement): Promise<DetectedBarcode[]> };
type BarcodeDetectorClass = new (options: { formats: string[] }) => BarcodeDetectorLike;

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr_code"];

function detectorClass(): BarcodeDetectorClass | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { BarcodeDetector?: BarcodeDetectorClass }).BarcodeDetector ?? null;
}

export function cameraScanningSupported(): boolean {
  return detectorClass() !== null && typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
}

/**
 * Point the phone's back camera at a barcode; the first code read is passed
 * to ``onDetected``. The camera is released as soon as this unmounts.
 */
export function CameraScanner({ onDetected }: { onDetected: (code: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<string | null>(() =>
    cameraScanningSupported() ? null : "This browser can't read barcodes with the camera. Use a barcode scanner or type the code.",
  );
  const done = useRef(false);

  useEffect(() => {
    const Detector = detectorClass();
    if (!Detector || problem) return;
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const detector = new Detector({ formats: FORMATS });

    async function scan() {
      const element = video.current;
      if (stopped || !element) return;
      try {
        if (element.readyState >= 2) {
          const [first] = await detector.detect(element);
          if (first?.rawValue && !done.current) {
            done.current = true;
            onDetected(first.rawValue.trim());
            return;
          }
        }
      } catch {
        // A frame that couldn't be read: try the next one.
      }
      timer = setTimeout(scan, 200);
    }

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
      .then((media) => {
        stream = media;
        if (stopped || !video.current) return;
        video.current.srcObject = media;
        void video.current.play().catch(() => undefined);
        void scan();
      })
      .catch((error: unknown) => {
        const denied = error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
        setProblem(denied ? "Camera access was blocked. Allow the camera for ShopFlow in your browser settings." : "Couldn't start the camera.");
      });

    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [onDetected, problem]);

  if (problem) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-6 text-center text-slate-700">
        <CameraOff aria-hidden="true" className="size-8 text-slate-500" />
        <p>{problem}</p>
      </div>
    );
  }
  return (
    <div className="relative overflow-hidden rounded-xl bg-slate-900">
      <video ref={video} muted playsInline className="aspect-[4/3] w-full object-cover" aria-label="Camera view" />
      {/* An aiming frame; the whole picture is searched, so it's only a guide. */}
      <div aria-hidden className="pointer-events-none absolute inset-x-8 top-1/2 h-24 -translate-y-1/2 rounded-lg border-2 border-emerald-300/90 shadow-[0_0_0_9999px_rgba(15,23,42,0.35)]" />
      <p className="absolute inset-x-0 bottom-2 text-center text-sm font-medium text-white">Hold the barcode inside the frame</p>
    </div>
  );
}
