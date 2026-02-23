import { useEffect, useRef, useState } from 'react';

interface ImageUploadProps {
  onImageSelect: (file: File) => void;
}

export default function ImageUpload({ onImageSelect }: ImageUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const isMobileDevice = () => {
    if (typeof navigator === 'undefined') return false;
    return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  };

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onImageSelect(file);
    }
    // Reset input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, []);

  useEffect(() => {
    if (!cameraError) return;
    const timer = setTimeout(() => setCameraError(null), 3500);
    return () => clearTimeout(timer);
  }, [cameraError]);

  const openCamera = async () => {
    setCameraError(null);
    // On mobile, captured-file input is more reliable than getUserMedia overlays.
    if (isMobileDevice()) {
      cameraInputRef.current?.click();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      cameraInputRef.current?.click();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
        },
        audio: false,
      });
      streamRef.current = stream;
      setCameraOpen(true);
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      }, 0);
    } catch {
      setCameraError('Camera permission denied or unavailable.');
      cameraInputRef.current?.click();
    }
  };

  const closeCamera = () => {
    setCameraOpen(false);
    stopCamera();
  };

  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.readyState < 2) {
      setCameraError('Camera is not ready yet. Please try again.');
      return;
    }
    const width = video.videoWidth || 1280;
    const height = video.videoHeight || 720;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, width, height);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
        onImageSelect(file);
        closeCamera();
      },
      'image/jpeg',
      0.92
    );
  };

  return (
    <div className="relative shrink-0">
      <div className="flex items-center gap-2">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleChange}
        className="hidden"
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleChange}
        className="hidden"
      />

      <button
        type="button"
        onClick={handleClick}
        className="p-1.5 sm:p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-600 rounded-lg transition-colors"
        title="Add image"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 5v14m-7-7h14"
          />
        </svg>
      </button>

      <button
        type="button"
        onClick={openCamera}
        className="p-1.5 sm:p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-600 rounded-lg transition-colors"
        title="Take photo"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 7h3l1.5-2h9L18 7h3v12H3V7z" />
          <circle cx="12" cy="13" r="4" />
        </svg>
      </button>

      </div>

      {cameraError && (
        <div className="absolute bottom-full left-0 mb-1 max-w-[220px] rounded-md border border-rose-500/40 bg-slate-900/95 px-2 py-1 text-[11px] text-rose-300 shadow-lg">
          {cameraError}
        </div>
      )}

      {cameraOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/85 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl p-3">
            <div className="aspect-video bg-black rounded-lg overflow-hidden">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              />
            </div>
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeCamera}
                className="px-3 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-slate-100 rounded-lg border border-slate-600"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={capturePhoto}
                className="px-3 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg"
              >
                Capture
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
