export const PWA_UPDATE_EVENT = 'pwa:update-available';

export interface PwaUpdateDetail {
  registration: ServiceWorkerRegistration;
}

function emitUpdateAvailable(registration: ServiceWorkerRegistration) {
  window.dispatchEvent(
    new CustomEvent<PwaUpdateDetail>(PWA_UPDATE_EVENT, {
      detail: { registration },
    }),
  );
}

function watchInstallingWorker(
  registration: ServiceWorkerRegistration,
  worker: ServiceWorker | null,
) {
  if (!worker) return;
  worker.addEventListener('statechange', () => {
    if (worker.state === 'installed' && navigator.serviceWorker.controller) {
      emitUpdateAvailable(registration);
    }
  });
}

export function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        watchInstallingWorker(registration, registration.installing);
        registration.addEventListener('updatefound', () => {
          watchInstallingWorker(registration, registration.installing);
        });
      })
      .catch(() => {
        // Keep app functional even if SW registration fails.
      });
  });
}
